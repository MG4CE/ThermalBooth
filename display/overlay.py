"""
Display overlay module for the photo booth.

Uses Picamera2's set_overlay() to composite countdown numbers and a white
flash on top of the DRM camera preview.  The overlay is an RGBA NumPy buffer
that the GPU blends on every vsync — Python only writes the buffer, so there
is zero impact on camera preview framerate.
"""

import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RGBA colour constants (alpha=255 unless noted)
# ---------------------------------------------------------------------------
WHITE      = (255, 255, 255, 255)
BLACK      = (  0,   0,   0, 255)
OUTLINE    = (  0,   0,   0, 220)  # slightly transparent black for text outlines
RED        = (220,  50,  50, 255)
YELLOW     = (255, 220,  50, 255)
GREEN      = ( 50, 200,  80, 255)
LIGHT_GRAY = (200, 200, 200, 255)

# Maps each countdown digit to its text colour
_COUNTDOWN_COLORS: dict = {
    3: RED,
    2: YELLOW,
    1: GREEN,
}


class Overlay:
    """
    Manages countdown and flash overlays rendered via the GPU compositor.

    All rendering happens into a NumPy RGBA array which is handed to
    ``camera.set_overlay()``.  No Pygame, no SDL, no per-frame blitting
    in Python — the hardware display pipeline does the compositing.
    """

    def __init__(self, camera, config: dict):
        """
        Args:
            camera: Camera instance (provides set_overlay / remove_overlay).
            config: Full application config dict (expects 'display' and 'camera' keys).
        """
        self.camera = camera
        disp_cfg = config.get('display', {})

        # Overlay dimensions match the preview window (portrait).
        self.width = disp_cfg.get('width', 600)
        self.height = disp_cfg.get('height', 1024)
        self.countdown_seconds = disp_cfg.get('countdown_seconds', 3)
        self.countdown_color = disp_cfg.get('countdown_color', True)
        self.flash_duration_ms = disp_cfg.get('flash_duration_ms', 150)
        self.result_display_s = disp_cfg.get('result_display_seconds', 3)
        self.font_size = disp_cfg.get('font_size', 200)
        self.show_status_messages = disp_cfg.get('show_status_messages', True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_countdown(self):
        """
        Display a 3-2-1 countdown overlay on the camera preview.

        Each number is rendered as a large centred digit coloured
        red → yellow → green (traffic-light convention) so it is readable
        over any scene.

        During the final second ("1"), the camera saturation is switched
        to full colour at the 0.5 s mark so the ISP has time to converge
        before capture — the countdown overlay hides the colour change.

        After the flash, the last captured B&W preview frame is held as an
        opaque overlay so the colour-saturated preview and the camera mode
        switch in capture() are never visible on screen.  The caller
        (Booth._capture_cycle) is responsible for clearing the overlay via
        overlay.clear() once capture is complete.
        """
        for i in range(self.countdown_seconds, 0, -1):
            color = _COUNTDOWN_COLORS.get(i, WHITE) if self.countdown_color else WHITE
            overlay = self._render_text(str(i), color=color)
            self.camera.set_overlay(overlay)
            if i == 1:
                # Sleep the first half of the last second normally.
                time.sleep(0.5)
                # Freeze the preview to the current B&W frame before changing
                # saturation.  From this point remove_overlay() will restore
                # the frozen frame rather than exposing the live feed, so the
                # white flash and camera mode-switch remain invisible.
                # Booth._capture_cycle calls camera.unfreeze_preview() after
                # capture() returns to release the freeze.
                self.camera.freeze_preview()
                self.camera.prepare_capture()
                time.sleep(0.3)
                self.flash_white()
            else:
                time.sleep(1)

    def flash_white(self):
        """
        Briefly flash the screen white (simulates a camera flash).

        Creates a fully-opaque white overlay, holds it for the configured
        duration, then removes it.
        """
        white = np.full((self.height, self.width, 4), 255, dtype=np.uint8)
        self.camera.set_overlay(white)
        time.sleep(self.flash_duration_ms / 1000.0)
        self.camera.remove_overlay()

    def show_processing(self):
        """Show a 'Processing…' message while the image is being prepared."""
        if not self.show_status_messages:
            return
        overlay = self._render_text("Processing", font_size=self.font_size // 3)
        self.camera.set_overlay(overlay)

    def show_printing(self):
        """Show a 'Printing…' message while the image is being printed."""
        if not self.show_status_messages:
            return
        overlay = self._render_text("Printing", font_size=self.font_size // 3)
        self.camera.set_overlay(overlay)

    def clear(self):
        """Remove any active overlay."""
        self.camera.remove_overlay()

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _render_text(
        self,
        text: str,
        font_size: Optional[int] = None,
        color: tuple = WHITE,
    ) -> np.ndarray:
        """
        Render *text* centred on a transparent RGBA overlay.

        Uses PIL for text rendering (single call, not per-frame) and
        converts to a NumPy array that Picamera2's overlay system expects.

        Args:
            text:      String to display.
            font_size: Override for the default font size.
            color:     RGBA tuple for the main text fill (default WHITE).

        Returns:
            NumPy array (H, W, 4) dtype=uint8 in RGBA order.
        """
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        fs = font_size or self.font_size

        # Fully transparent background — overlay blends over the live preview
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Load a bold font; fall back to default if unavailable
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fs
            )
        except Exception:
            font = ImageFont.load_default()

        # Pixel-perfect centering: subtract the bbox origin so glyphs with
        # a non-zero ascent baseline don't drift upward.
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (self.width  - tw) // 2 - bbox[0]
        y = (self.height - th) // 2 - bbox[1]

        # Black outline for readability over any scene
        outline = max(3, fs // 30)
        for dx in range(-outline, outline + 1):
            for dy in range(-outline, outline + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, fill=OUTLINE, font=font)

        # Main text in the requested colour
        draw.text((x, y), text, fill=color, font=font)

        return np.array(img, dtype=np.uint8)
