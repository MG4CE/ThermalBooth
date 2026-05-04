"""
Camera module for Raspberry Pi using Picamera2.
Uses DRM/KMS hardware-accelerated preview for zero-overhead fullscreen display.
All image adjustments are applied natively via libcamera controls — no per-frame
Python processing — ensuring maximum preview performance with no dropped frames.
"""

import os
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2, Preview  # type: ignore
    from libcamera import controls as libcamera_controls  # type: ignore
    from libcamera import Transform  # type: ignore
    PICAMERA2_AVAILABLE = True
except ImportError as e:
    logger.error(f"Picamera2 import failed: {e}")
    PICAMERA2_AVAILABLE = False


class Camera:
    """
    Raspberry Pi camera wrapper using Picamera2 with DRM/KMS preview.
    
    The preview runs entirely on the GPU via the DRM hardware compositor,
    meaning Python never touches individual frames during preview. This
    gives the best possible framerate with zero CPU overhead for display.
    
    Camera adjustments (brightness, contrast, saturation, denoise) are
    configured as native libcamera controls so the ISP handles them in
    hardware, not in software.
    """

    def __init__(self, config: dict):
        """
        Initialize camera with configuration.

        Args:
            config: Full application config dict (expects 'camera' key)
        """
        self.cam_config = config.get('camera', {})
        disp_config = config.get('display', {})

        # Display dimensions (portrait: 600×1024).
        # For QTGL preview the Qt window can be any size — the compositor
        # handles rotation / scaling.  For DRM fallback we swap to landscape
        # to match the CRTC mode.
        self.preview_width = disp_config.get('width', 600)
        self.preview_height = disp_config.get('height', 1024)
        self.fullscreen = disp_config.get('fullscreen', True)

        self.framerate = self.cam_config.get('framerate', 24)
        color_preview = self.cam_config.get('color_preview', False)
        self.preview_saturation = 1.0 if color_preview else 0.0
        self.brightness = self.cam_config.get('brightness', 0.0)
        self.contrast = self.cam_config.get('contrast', 1.0)
        self.exposure_value = self.cam_config.get('exposure_value', 0.0)
        self.denoise = self.cam_config.get('denoise', 'cdn_hq')
        self.sharpness = self.cam_config.get('sharpness', 1.5)
        self.autofocus = self.cam_config.get('autofocus', True)
        self.raw_width = self.cam_config.get('raw_width', 2304)
        self.raw_height = self.cam_config.get('raw_height', 1296)
        self.capture_width = self.cam_config.get('capture_width', 3500)
        self.capture_height = self.cam_config.get('capture_height', 2550)
        self.jpeg_quality = self.cam_config.get('jpeg_quality', 92)

        self.picam2: Optional[Picamera2] = None
        self._preview_config = None
        self._capture_config = None
        self._running = False
        self._frozen_overlay = None  # set by freeze_preview(), cleared by unfreeze_preview()

        if not PICAMERA2_AVAILABLE:
            logger.warning("Picamera2 not available — camera will run in simulation mode")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_preview(self):
        """
        Configure and start the fullscreen DRM preview.

        The preview stream resolution matches the DRM CRTC mode (1024×600)
        so the GPU compositor can scan-out directly with no scaling overhead.
        A separate *still* configuration is prepared for high-res capture so
        we can switch into it momentarily when the shutter fires.
        """
        if not PICAMERA2_AVAILABLE:
            logger.warning("[Camera] Simulation mode — no preview started")
            self._running = True
            return

        self.picam2 = Picamera2()

        # Log sensor modes to help debug DRM commit failures
        sensor_modes = self.picam2.sensor_modes
        logger.info(f"[Camera] Available sensor modes:")
        for i, mode in enumerate(sensor_modes):
            logger.info(f"  [{i}] {mode}")

        # ----- Determine the full-resolution sensor mode -----
        # Lock both preview and still to the SAME sensor mode so the ISP
        # uses the same crop (= same FOV).  The preview stream is just a
        # downscale of the full sensor output, not a different crop.
        sensor_modes = self.picam2.sensor_modes
        # Pick the mode with the largest area (full-res, widest FOV)
        full_mode = max(sensor_modes, key=lambda m: m["size"][0] * m["size"][1])
        sensor_size = full_mode["size"]
        logger.info(f"[Camera] Using sensor mode: {sensor_size} for both preview and capture")

        # ----- Preview (video) configuration -----
        # Use XBGR8888 (32-bit) format — VC4 DRM planes require 32-bit.
        # Preview is portrait (600×1024) for QTGL.  If we fall back to DRM
        # we'll reconfigure to landscape below.
        preview_size = (self.preview_width, self.preview_height)
        self._preview_config = self.picam2.create_preview_configuration(
            main={"size": preview_size, "format": "XBGR8888"},
            raw={"size": (self.raw_width, self.raw_height)},
            buffer_count=4,
            controls={
                "FrameDurationLimits": (int(1_000_000 / self.framerate),
                                        int(1_000_000 / self.framerate)),
                #**self._isp_controls(self.preview_saturation),
            },
        )

        # Log what Picamera2 actually chose (it may adjust our request)
        logger.info(f"[Camera] Requested preview size: {preview_size}")
        logger.info(f"[Camera] Preview config: {self._preview_config}")

        # ----- Still (capture) configuration -----
        # Still capture at full sensor resolution (IMX708: 4608×2592).
        # Saturation 1.0 ensures the captured image is full colour even
        # though the preview runs desaturated (B&W).
        self._capture_config = self.picam2.create_still_configuration(
            main={"size": (self.capture_width, self.capture_height), "format": "RGB888"},
            sensor={"output_size": sensor_size},
            controls={
                "Saturation": 1.0,
                "AeMeteringMode": libcamera_controls.AeMeteringModeEnum.Spot,
                "ExposureValue": float(self.exposure_value),
                "Brightness": float(self.brightness),
                "Contrast": float(self.contrast),
            },
        )

        self.picam2.configure(self._preview_config)
        logger.info(f"[Camera] Configuration applied. Main stream: "
                     f"{self.picam2.camera_configuration()['main']}")

        # Choose preview backend.
        # If a desktop compositor is running (Wayfire / labwc / X11) it
        # already owns the DRM primary plane, so DRM preview will "start"
        # but every frame commit silently fails.  Detect a running desktop
        # by checking common env vars and prefer QTGL in that case.
        # QTGL opens a GPU-accelerated window inside the desktop session.
        # When no desktop is running (console / kiosk mode) DRM gives
        # zero-overhead fullscreen with no compositor needed.
        import subprocess
        desktop_running = bool(os.environ.get("WAYLAND_DISPLAY")
                               or os.environ.get("DISPLAY"))
        if not desktop_running:
            # Double-check: a display manager might be running without
            # setting env vars in this shell (e.g. started via systemd).
            try:
                r = subprocess.run(["pgrep", "-x", "wayfire|labwc|weston|Xorg|xfwm4"],
                                   capture_output=True, timeout=2)
                if r.returncode == 0:
                    desktop_running = True
            except Exception:
                pass

        preview_started = False

        if desktop_running:
            logger.info("[Camera] Desktop session detected — using QTGL preview")
            try:
                self.picam2.start_preview(Preview.QTGL,
                                           x=0, y=0,
                                           width=self.preview_width,
                                           height=self.preview_height)
                logger.info("[Camera] QTGL preview started successfully")
                preview_started = True

                if self.fullscreen:
                    self._make_qtgl_fullscreen()
                else:
                    logger.info(f"[Camera] QTGL preview in windowed mode ({self.preview_width}×{self.preview_height})")
            except Exception as e:
                logger.error(f"[Camera] QTGL preview failed: {e}")

        if not preview_started:
            # No desktop or QTGL failed — try DRM (works in console mode).
            # DRM requires buffer dimensions to match the CRTC mode exactly
            # (1024×600 landscape), so reconfigure with swapped dimensions.
            try:
                drm_w, drm_h = self.preview_height, self.preview_width  # swap to landscape
                drm_config = self.picam2.create_preview_configuration(
                    main={"size": (drm_w, drm_h), "format": "XBGR8888"},
                    buffer_count=4,
                    controls={
                        "FrameDurationLimits": (int(1_000_000 / self.framerate),
                                                int(1_000_000 / self.framerate)),
                        **self._isp_controls(self.preview_saturation),
                    },
                )
                self.picam2.configure(drm_config)
                self.picam2.start_preview(Preview.DRM)
                logger.info(f"[Camera] DRM preview started at {drm_w}×{drm_h} (landscape for CRTC)")
                preview_started = True
            except Exception as e:
                logger.error(f"[Camera] DRM preview failed: {e}")

        if not preview_started:
            logger.warning("[Camera] All previews failed — using NULL (capture still works)")
            self.picam2.start_preview(Preview.NULL)

        self.picam2.start()

        # Apply native libcamera controls — handled by the ISP, not Python
        self._apply_native_controls()

        self._running = True
        logger.info(f"[Camera] DRM preview started at {self.preview_width}×{self.preview_height} "
                     f"@ {self.framerate}fps")

    def _make_qtgl_fullscreen(self):
        """Make the QTGL preview window fullscreen without decorations.

        IMPORTANT: we must NOT call setWindowFlags() — that destroys and
        recreates the native window handle, which kills the OpenGL context
        that Picamera2 is rendering into (window appears then vanishes).

        Instead we use showFullScreen(), which asks the compositor (Wayfire /
        labwc / X11 WM) to promote the existing window to fullscreen mode.
        Most compositors automatically strip decorations for fullscreen
        windows.
        """
        try:
            from PyQt5.QtWidgets import QApplication  # type: ignore

            app = QApplication.instance()
            if app is None:
                logger.debug("[Camera] No QApplication instance found")
                return

            for widget in app.topLevelWidgets():
                if widget.isVisible():
                    widget.showFullScreen()
                    logger.info("[Camera] QTGL window set to fullscreen")
                    break
        except ImportError:
            logger.debug("[Camera] PyQt5 not available — cannot fullscreen window")
        except Exception as e:
            logger.debug(f"[Camera] Could not set fullscreen: {e}")

    def _isp_controls(self, saturation: float) -> dict:
        """Build the full ISP controls dict for a given saturation level.

        Used both when baking controls into the camera configuration and
        when calling set_controls() on a running camera, so all settings
        are always consistent between preview, DRM fallback, and capture.
        """
        ctrl: dict = {
            # Brightness: libcamera range roughly -1.0 … 1.0
            "Brightness": float(self.brightness),
            # Contrast: 1.0 = normal
            "Contrast": float(self.contrast),
            # Saturation: 0.0 = greyscale, 1.0 = full colour
            "Saturation": float(saturation),
            # Auto-exposure
            "AeEnable": True,
            "ExposureValue": float(self.exposure_value),  # positive = brighter, negative = darker
            "AeMeteringMode": libcamera_controls.AeMeteringModeEnum.Spot,
            "AeExposureMode": libcamera_controls.AeExposureModeEnum.Normal,
            # Auto white balance
            "AwbMode": 0,
            # Sharpening
            "Sharpness": float(self.sharpness),
        }

        # Noise reduction
        denoise_map = {
            "cdn_off": libcamera_controls.draft.NoiseReductionModeEnum.Off
                       if hasattr(libcamera_controls, 'draft') else 0,
            "cdn_fast": libcamera_controls.draft.NoiseReductionModeEnum.Fast
                        if hasattr(libcamera_controls, 'draft') else 1,
            "cdn_hq": libcamera_controls.draft.NoiseReductionModeEnum.HighQuality
                      if hasattr(libcamera_controls, 'draft') else 2,
        }
        noise_mode = denoise_map.get(self.denoise)
        if noise_mode is not None:
            ctrl["NoiseReductionMode"] = noise_mode

        # Autofocus — IMX708 has PDAF; older sensors ignore these gracefully.
        if self.autofocus:
            try:
                ctrl["AfMode"] = libcamera_controls.AfModeEnum.Continuous
                ctrl["AfSpeed"] = libcamera_controls.AfSpeedEnum.Fast
            except AttributeError:
                logger.debug("[Camera] Autofocus controls not available for this sensor")

        return ctrl

    def _apply_native_controls(self):
        """Push ISP controls onto the running camera via set_controls()."""
        if not self.picam2:
            return
        ctrl = self._isp_controls(self.preview_saturation)
        try:
            self.picam2.set_controls(ctrl)
            logger.info(f"[Camera] Native controls applied: {ctrl}")
        except Exception as e:
            logger.warning(f"[Camera] Could not apply some controls: {e}")

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture(self, output_path: str) -> str:
        """
        Capture a full-resolution still image.

        Uses switch_mode_and_capture_file() which briefly switches to the
        still configuration, captures one frame, and switches back to preview
        mode.  The preview stream continues to run during the mode switch so
        the display does not freeze.

        Saturation is pre-set to 1.0 by prepare_capture() during the last
        countdown second, so the ISP is already converged by the time this
        method runs.  After capture, saturation is restored to the preview
        value (0.0) so the live preview remains in black-and-white.

        Args:
            output_path: File path to save the captured JPEG.

        Returns:
            The path to the saved image.
        """
        if not PICAMERA2_AVAILABLE or not self.picam2:
            logger.warning("[Camera] Simulation mode — generating dummy capture")
            return self._simulate_capture(output_path)

        logger.info("[Camera] Capturing full-resolution still…")

        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Saturation is already set to 1.0 during the countdown
        # (prepare_capture), so no wait needed here.

        try:
            self.picam2.switch_mode_and_capture_file(
                self._capture_config, output_path,
                signal_function=None
            )
            # Re-save with desired JPEG quality if needed
            if output_path.lower().endswith(('.jpg', '.jpeg')) and self.jpeg_quality != 95:
                from PIL import Image as PILImage
                img = PILImage.open(output_path)
                img.save(output_path, quality=self.jpeg_quality)
            logger.info(f"[Camera] Still saved to {output_path} (quality={self.jpeg_quality})")
        finally:
            # Restore the preview saturation
            self.picam2.set_controls({"Saturation": float(self.preview_saturation)})
            logger.debug(f"[Camera] Saturation restored to {self.preview_saturation} for preview")
            # set_controls() is asynchronous — the ISP needs a few frames to
            # converge to the new saturation value.  Sleep for 3 frame durations
            # so the live feed is already B&W by the time unfreeze_preview()
            # removes the frozen overlay and exposes the preview.
            time.sleep(4 / self.framerate)

        return output_path

    def _simulate_capture(self, output_path: str) -> str:
        """Create a dummy image for simulation/testing mode."""
        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore
            img = Image.new("RGB", (self.capture_width, self.capture_height), (128, 128, 128))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
            except Exception:
                font = ImageFont.load_default()
            draw.text((self.capture_width // 4, self.capture_height // 2 - 40),
                       "SIMULATED CAPTURE", fill="white", font=font)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            img.save(output_path)
        except Exception as e:
            logger.error(f"[Camera] Could not create dummy image: {e}")
            # Create a minimal placeholder
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            from PIL import Image  # type: ignore
            Image.new("RGB", (640, 480), (0, 0, 0)).save(output_path)

        return output_path

    # ------------------------------------------------------------------
    # Overlay (used by display module for countdown / flash)
    # ------------------------------------------------------------------

    def set_overlay(self, array):
        """
        Push an RGBA NumPy array as a GPU overlay on top of the DRM preview.

        This is composited by the hardware display pipeline — Python only
        constructs the overlay buffer; the GPU does the blending on every
        vsync, so there is zero impact on the camera preview framerate.

        Args:
            array: NumPy array of shape (height, width, 4) dtype=uint8 (RGBA).
        """
        if not PICAMERA2_AVAILABLE or not self.picam2:
            return
        try:
            self.picam2.set_overlay(array)
        except Exception as e:
            logger.debug(f"[Camera] Overlay error: {e}")

    def remove_overlay(self):
        """Remove the current overlay (make it fully transparent).

        If the preview is currently frozen via freeze_preview(), restores the
        frozen frame instead of exposing the live feed.  This ensures that
        intermediate callers (e.g. flash_white) cannot accidentally reveal a
        colour-saturated preview frame between the flash and capture.
        """
        if not PICAMERA2_AVAILABLE or not self.picam2:
            return
        if self._frozen_overlay is not None:
            # Stay frozen — restore the held frame rather than going live.
            try:
                self.picam2.set_overlay(self._frozen_overlay)
            except Exception as e:
                logger.debug(f"[Camera] Restore frozen overlay error: {e}")
            return
        try:
            self.picam2.set_overlay(None)
        except Exception as e:
            logger.debug(f"[Camera] Remove overlay error: {e}")

    def freeze_preview(self):
        """Freeze the visible preview to the current B&W frame.

        Grabs the latest frame from the preview stream and holds it as a
        fully-opaque overlay, so any subsequent ISP changes (saturation,
        mode-switch) are invisible to the viewer.  Also overrides
        remove_overlay() to restore this frame rather than exposing the
        live feed, which means callers like flash_white() work correctly
        without any modifications.

        Call unfreeze_preview() to release the freeze and return to the
        live feed.
        """
        frame = self.get_preview_frame_rgba()
        if frame is not None:
            self._frozen_overlay = frame
            self.set_overlay(frame)
            logger.debug("[Camera] Preview frozen")
        else:
            logger.warning("[Camera] freeze_preview: could not grab frame, preview not frozen")

    def unfreeze_preview(self):
        """Release the frozen frame and return to the live preview.

        Clears the frozen-frame state and removes the overlay so the GPU
        compositor shows the live camera feed again.
        """
        self._frozen_overlay = None
        try:
            if self.picam2:
                self.picam2.set_overlay(None)
        except Exception as e:
            logger.debug(f"[Camera] Unfreeze overlay error: {e}")
        logger.debug("[Camera] Preview unfrozen")

    def get_preview_frame_rgba(self) -> "Optional[np.ndarray]":
        """
        Grab the current preview frame as a fully-opaque RGBA NumPy array.

        Intended to freeze the visible output before a camera mode-switch
        (or saturation change) that would otherwise cause a brief colour
        flash on-screen.  The returned array can be fed directly to
        set_overlay() to hold that frame until capture is complete.

        The preview stream uses XBGR8888 (little-endian), so in memory the
        byte order is R, G, B, X — identical to RGBA except the last byte.
        We copy the buffer and force the last channel to 255 (fully opaque).

        Returns:
            NumPy array (H, W, 4) dtype=uint8 in RGBA order, or None if
            Picamera2 is unavailable or the frame grab fails.
        """
        if not PICAMERA2_AVAILABLE or not self.picam2:
            return None
        try:
            import numpy as np
            frame = self.picam2.capture_array("main")  # (H, W, 4), XBGR8888
            rgba = frame.copy()
            rgba[:, :, 3] = 255  # force fully opaque alpha
            return rgba
        except Exception as e:
            logger.warning(f"[Camera] Could not grab preview frame for freeze: {e}")
            return None

    def prepare_capture(self):
        """Set saturation to 1.0 so the ISP converges before the actual capture.

        Call this ~0.5 s before capture() while an overlay is still hiding
        the preview so the user never sees the colour flash.
        """
        if not PICAMERA2_AVAILABLE or not self.picam2:
            return
        self.picam2.set_controls({"Saturation": 1.0})
        logger.debug("[Camera] Saturation pre-set to 1.0 for upcoming capture")

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def stop(self):
        """Stop the camera preview and release resources."""
        self._running = False
        if self.picam2:
            try:
                self.picam2.stop_preview()
                self.picam2.stop()
                self.picam2.close()
                logger.info("[Camera] Camera stopped and released")
            except Exception as e:
                logger.error(f"[Camera] Error stopping camera: {e}")
            finally:
                self.picam2 = None

    @property
    def is_running(self) -> bool:
        return self._running
