#!/usr/bin/env python3
"""
ThermalBooth — Raspberry Pi Camera Photo Booth
==================================================

Entry-point and state machine for the photo booth application.

States
------
IDLE      — Fullscreen DRM camera preview is running. Waiting for shutter trigger.
COUNTDOWN — 3-2-1 overlay countdown on top of the live preview.
CAPTURE   — Flash the screen white, capture a full-resolution still.
PROCESS   — Enhance the image and apply dithering for thermal printing.
PRINT     — Send the processed image to the thermal printer.

After PRINT the machine returns to IDLE and waits for the next trigger.

Controls
--------
- **GPIO button** (pin from config)  →  trigger shutter
- **Spacebar**                       →  trigger shutter
- **Escape**                         →  quit the application
"""

import json
import logging
import os
import sys
import tempfile
import threading
import time
import signal

# ---------------------------------------------------------------------------
# Logging — configure before importing any project modules
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("booth")

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from camera.pi_cam_module_3 import Camera
from display.overlay import Overlay
from image.handler import ImageHandler
from printer.manager import PrinterManager
from input.gpio import GPIOHandler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


# ═══════════════════════════════════════════════════════════════════════════
# Booth — main application class
# ═══════════════════════════════════════════════════════════════════════════

class Booth:
    """Photo booth state machine."""

    # States
    IDLE = "IDLE"
    COUNTDOWN = "COUNTDOWN"
    CAPTURE = "CAPTURE"
    PROCESS = "PROCESS"
    PRINT = "PRINT"

    def __init__(self):
        # Load config
        with open(CONFIG_PATH, "r") as f:
            self.config = json.load(f)

        self.state = self.IDLE
        self._busy = False  # prevents re-entrance during a capture cycle
        self._quit = False

        # --- Subsystems -------------------------------------------------------
        logger.info("Initialising camera…")
        self.camera = Camera(self.config)

        logger.info("Initialising display overlay…")
        self.overlay = Overlay(self.camera, self.config)

        logger.info("Initialising image handler…")
        self.image_handler = ImageHandler(config_path=CONFIG_PATH)

        logger.info("Initialising printer…")
        self.printer = PrinterManager(config_path=CONFIG_PATH)

        logger.info("Initialising GPIO…")
        self.gpio = GPIOHandler(config_path=CONFIG_PATH, callback=self._trigger)


    # ------------------------------------------------------------------
    # Run loop (blocking)
    # ------------------------------------------------------------------

    def run(self):
        """
        Start the camera preview and enter the main event loop.

        The loop listens for keyboard events via ``/dev/input`` (evdev) so
        that we can detect Spacebar and Escape without needing a focused
        window / Pygame / SDL.  If evdev is not available we fall back to a
        simple stdin-based approach (useful during development over SSH).
        """
        # Start the DRM preview — GPU-composited, zero CPU overhead
        self.camera.start_preview()
        logger.info("Photo booth is running. Press SPACE to capture, ESC to quit.")

        # Try evdev for headless key reading (preferred on the RPi with DRM)
        try:
            self._run_evdev_loop()
        except ImportError:
            logger.warning("evdev not available — falling back to terminal input loop")
            self._run_fallback_loop()

    # ---- evdev keyboard loop (preferred) ---------------------------------

    def _run_evdev_loop(self):
        """Read keyboard events via evdev (works without X11 / Wayland)."""
        import evdev  # type: ignore
        from evdev import ecodes  # type: ignore
        import selectors

        # Find real keyboard devices — filter out HDMI CEC / virtual devices
        # by requiring the device to have common alpha-numeric keys.
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        keyboards = []
        for d in devices:
            caps = d.capabilities().get(ecodes.EV_KEY, [])
            # A real keyboard will have KEY_A (30) and KEY_SPACE (57)
            if ecodes.KEY_A in caps and ecodes.KEY_SPACE in caps:
                keyboards.append(d)
                logger.info(f"Found keyboard: {d.name} ({d.path})")

        if not keyboards:
            # Fallback: accept any device with EV_KEY if the strict filter
            # found nothing (e.g. minimal HID device / barcode scanner)
            keyboards = [d for d in devices
                         if ecodes.EV_KEY in d.capabilities()]
            if keyboards:
                logger.warning("No standard keyboard found — using first EV_KEY device")

        if not keyboards:
            raise ImportError("No keyboard devices found via evdev")

        logger.info(f"Listening on {len(keyboards)} keyboard(s)")

        # Use selectors to listen on ALL keyboards simultaneously
        sel = selectors.DefaultSelector()
        for kbd in keyboards:
            sel.register(kbd, selectors.EVENT_READ)

        try:
            while not self._quit:
                events = sel.select(timeout=0.2)
                for key, _ in events:
                    kbd = key.fileobj
                    for event in kbd.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        if event.value != 1:  # key-down only
                            continue

                        if event.code == ecodes.KEY_SPACE:
                            self._trigger()
                        elif event.code == ecodes.KEY_ESC:
                            logger.info("ESC pressed — shutting down")
                            self._quit = True
                            break
                    if self._quit:
                        break
        except KeyboardInterrupt:
            pass
        finally:
            sel.close()
            for d in keyboards:
                try:
                    d.close()
                except Exception:
                    pass
            self.shutdown()

    # ---- Fallback loop (for SSH / development) ---------------------------

    def _run_fallback_loop(self):
        """Simple blocking loop using select + stdin (for development)."""
        import select as _select
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            logger.info("Terminal input mode: press SPACE to capture, ESC / q to quit")
            while not self._quit:
                rlist, _, _ = _select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == " ":
                        self._trigger()
                    elif ch in ("\x1b", "q"):
                        logger.info("Quit key pressed — shutting down")
                        self._quit = True
        except KeyboardInterrupt:
            pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            self.shutdown()

    # ------------------------------------------------------------------
    # Trigger → capture cycle (runs in a thread so input loop isn't blocked)
    # ------------------------------------------------------------------

    def _trigger(self):
        """Called by GPIO press or keyboard Spacebar."""
        if self._busy:
            logger.debug("Trigger ignored — capture cycle already in progress")
            return
        # Run the capture pipeline in a background thread so the input
        # loop stays responsive (and the DRM preview keeps updating).
        threading.Thread(target=self._capture_cycle, daemon=True).start()

    def _capture_cycle(self):
        """Execute the full COUNTDOWN → CAPTURE → PROCESS → PRINT pipeline."""
        self._busy = True
        try:
            # Create a temporary file for the raw capture
            capture_fd, photo_path = tempfile.mkstemp(suffix=".jpg", prefix="capture_")
            os.close(capture_fd)

            # ---- COUNTDOWN ----
            self.state = self.COUNTDOWN
            logger.info("Starting countdown…")
            self.overlay.show_countdown()

            # ---- CAPTURE ----
            self.state = self.CAPTURE
            logger.info("Capturing photo…")
            #self.overlay.flash_white()

            self.camera.capture(photo_path)
            
            # Release the frozen frame now that the mode-switch is done.
            # Saturation is already restored to B&W inside camera.capture().
            self.camera.unfreeze_preview()
            logger.info(f"Photo saved to {photo_path}")

            # ---- PROCESS ----
            self.state = self.PROCESS
            self.overlay.show_processing()
            logger.info("Processing image…")

            processed_path, w, h = self.image_handler.process_captured_photo(photo_path)
            logger.info(f"Processed image: {processed_path} ({w}×{h})")

            # ---- PRINT ----
            self.state = self.PRINT
            self.overlay.show_printing()
            logger.info("Printing…")

            success = self.printer.print_image(processed_path)
            if success:
                logger.info("Print complete ✓")
            else:
                logger.warning("Print failed (see printer logs)")
            # Clean up temporary files
            for tmp in (photo_path, processed_path):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            # Brief pause so the user sees the status message
            time.sleep(self.config.get('display', {}).get('result_display_seconds', 3))

        except Exception as e:
            logger.error(f"Capture cycle error: {e}", exc_info=True)
        finally:
            # Return to idle
            self.overlay.clear()
            self.state = self.IDLE
            self._busy = False

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        """Cleanly tear down all subsystems."""
        logger.info("Shutting down…")
        self._quit = True
        self.overlay.clear()
        self.camera.stop()
        self.gpio.cleanup()
        self.printer.disconnect()
        logger.info("Goodbye.")


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    booth = Booth()

    # Handle SIGINT / SIGTERM gracefully
    def _sig_handler(signum, frame):
        booth.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    booth.run()


if __name__ == "__main__":
    main()
