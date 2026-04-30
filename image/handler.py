"""
Image processing module for thermal printer photo booth.
Handles image enhancement, dithering, resizing, and debug output.
"""

import os
import json
import logging
import tempfile
import uuid
from PIL import Image, ImageOps  # type: ignore
from typing import Tuple, Optional
from image.processor import ImageProcessor, DitheringMethod

logger = logging.getLogger(__name__)


class ImageHandler:
    """Process captured photos for thermal printer output."""

    def __init__(self, config_path='config.json'):
        """Initialize image handler with configuration."""
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.DEBUG_DIR = os.path.join(project_root, self.config.get('debug_dir', 'debug'))

        self.print_width = self.config['printer'].get('print_width', 384)
        self.image_processor = ImageProcessor()

        # Header / footer images (printed above / below the photo)
        self.header_img = self._load_border_image(
            self.config['image_settings'].get('header_image', ''),
            self.config['image_settings'].get('header_max_height', 0))
        self.footer_img = self._load_border_image(
            self.config['image_settings'].get('footer_image', ''),
            self.config['image_settings'].get('footer_max_height', 0))
        self.header_gap = self.config['image_settings'].get('header_gap', 0)
        self.footer_gap = self.config['image_settings'].get('footer_gap', 0)

        # Debug flag
        self.save_debug = self.config.get('save_debug_images', False)

        # Ensure debug directory exists if needed
        if self.save_debug:
            os.makedirs(self.DEBUG_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Main entry point — called by the booth state machine
    # ------------------------------------------------------------------

    def process_captured_photo(self, photo_path: str,
                                dither_method: Optional[str] = None,
                                raw_mode: bool = False) -> Tuple[str, int, int]:
        """
        Full pipeline for a freshly-captured photo:
            1. Fix EXIF orientation
            2. (debug) save raw capture
            3. Convert to greyscale → dither → resize to print_width
            4. (debug) save dithered image
            5. Return path to the print-ready file

        Args:
            photo_path: Path to the JPEG from the camera.
            dither_method: Dithering algorithm name (default from config).
            raw_mode: If True skip dithering — keep original colour/format.

        Returns:
            (processed_path, width, height)
        """
        image_id = str(uuid.uuid4())

        # Load & fix orientation
        img = Image.open(photo_path)
        img = ImageOps.exif_transpose(img)

        # ---- debug: raw capture ----
        if self.save_debug:
            self._save_debug(img, image_id, "raw")

        # RAW mode — just resize to print width, keep colour
        if raw_mode:
            return self._process_raw(img, image_id)

        # ---- Resize to print width FIRST ----
        # Doing this before enhancement/dithering is critical for speed.
        # Processing a 576px-wide image is ~20x faster than processing
        # the full-resolution capture.
        img = self._resize_to_width(img, self.print_width)
        logger.debug(f"[ImageHandler] Resized to print width: {img.width}x{img.height}")

        # ---- Greyscale + dither ----
        img_grey = img.convert('L')

        method = dither_method or self.config['image_settings'].get(
            'dither_method', DitheringMethod.FLOYD_STEINBERG
        )
        img_dithered = self.image_processor.apply_dithering(img_grey, method)

        if self.save_debug:
            self._save_debug(img_dithered, image_id, "dithered")

        img_print = img_dithered

        # ---- Attach header / footer images ----
        img_print = self._attach_borders(img_print)

        # Save to a temporary file for the printer
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img_print.save(tmp.name)
        tmp.close()

        logger.info(f"[ImageHandler] Processed {image_id} → {tmp.name} "
                     f"({img_print.width}×{img_print.height})")
        return tmp.name, img_print.width, img_print.height

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resize_to_width(self, img: Image.Image, target_width: int) -> Image.Image:
        """Resize image to *target_width* while preserving aspect ratio."""
        if img.width == target_width:
            return img
        aspect = img.height / img.width
        new_h = int(target_width * aspect)
        return img.resize((target_width, new_h), Image.Resampling.LANCZOS)

    def _load_border_image(self, path: str, max_height: int = 0) -> Optional[Image.Image]:
        """Load and pre-scale a header/footer image to print_width.

        The image is scaled to print_width first, then if max_height > 0
        and the image is taller, it is downscaled to fit within max_height
        (preserving aspect ratio).  Finally converted to 1-bit so it
        composites cleanly with the dithered photo.

        Returns None if the path is empty or the file cannot be loaded.
        """
        if not path:
            return None
        # Resolve relative paths from project root
        if not os.path.isabs(path):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(project_root, path)
        if not os.path.exists(path):
            logger.warning(f"[ImageHandler] Border image not found: {path}")
            return None
        try:
            img = Image.open(path)
            img = self._resize_to_width(img, self.print_width)
            # Enforce max height — downscale proportionally if too tall
            if max_height > 0 and img.height > max_height:
                scale = max_height / img.height
                new_w = int(img.width * scale)
                img = img.resize((new_w, max_height), Image.Resampling.LANCZOS)
                logger.debug(f"[ImageHandler] Border image capped to {new_w}x{max_height}px")
            # Convert to 1-bit to match the dithered photo
            if img.mode != '1':
                img = img.convert('L').convert('1')
            logger.info(f"[ImageHandler] Loaded border image: {path} ({img.width}x{img.height})")
            return img
        except Exception as e:
            logger.error(f"[ImageHandler] Failed to load border image '{path}': {e}")
            return None

    def _attach_borders(self, img: Image.Image) -> Image.Image:
        """Vertically stack header (top) + gap + photo + gap + footer (bottom).

        Border images are centered horizontally on the print_width canvas
        if they are narrower (e.g. after max_height downscaling).  The
        result is a single 1-bit image ready for the printer.

        Gaps (white space) between header/photo and photo/footer are
        controlled by ``header_gap`` and ``footer_gap`` in config (pixels).
        """
        if not self.header_img and not self.footer_img:
            return img

        total_h = img.height
        if self.header_img:
            total_h += self.header_img.height + self.header_gap
        if self.footer_img:
            total_h += self.footer_img.height + self.footer_gap

        # Create a white canvas (1-bit: 1 = white)
        composite = Image.new('1', (self.print_width, total_h), 1)

        y = 0
        if self.header_img:
            x = (self.print_width - self.header_img.width) // 2
            composite.paste(self.header_img, (x, y))
            y += self.header_img.height + self.header_gap

        x = (self.print_width - img.width) // 2
        composite.paste(img, (x, y))
        y += img.height

        if self.footer_img:
            y += self.footer_gap
            x = (self.print_width - self.footer_img.width) // 2
            composite.paste(self.footer_img, (x, y))

        logger.debug(f"[ImageHandler] Composited borders: {composite.width}x{composite.height}")
        return composite

    def _process_raw(self, img: Image.Image, image_id: str) -> Tuple[str, int, int]:
        """Resize to print_width keeping colour, save to temp file, return path."""
        img = self._resize_to_width(img, self.print_width)
        tmp = tempfile.NamedTemporaryFile(suffix="_raw.png", delete=False)
        img.save(tmp.name)
        tmp.close()
        logger.info(f"[ImageHandler] Raw processed {image_id} → {tmp.name}")
        return tmp.name, img.width, img.height

    def _save_debug(self, img: Image.Image, image_id: str, stage: str):
        """Save a debug snapshot for inspection."""
        ext = "png" if img.mode == "1" else "jpg"
        path = os.path.join(self.DEBUG_DIR, f"{image_id}_{stage}.{ext}")
        img.save(path)
        logger.debug(f"[ImageHandler] Debug image saved: {path}")

    def get_print_width(self) -> int:
        """Get configured print width in pixels."""
        return self.print_width
