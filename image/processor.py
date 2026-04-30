"""
Image dithering processor for thermal printer output.
Provides multiple dithering algorithms for converting greyscale images
to 1-bit (black and white) suitable for thermal printing.
"""

import logging
from PIL import Image  # type: ignore

logger = logging.getLogger(__name__)


class DitheringMethod:
    """Constants for available dithering methods."""
    FLOYD_STEINBERG = "floyd_steinberg"
    ATKINSON = "atkinson"
    THRESHOLD = "threshold"
    NONE = "none"


class ImageProcessor:
    """Apply dithering algorithms to greyscale images."""

    def apply_dithering(self, img: Image.Image, method: str = DitheringMethod.FLOYD_STEINBERG) -> Image.Image:
        """
        Apply a dithering algorithm to a greyscale image.

        Args:
            img: Greyscale (mode 'L') PIL Image.
            method: Dithering method name (see DitheringMethod constants).

        Returns:
            1-bit (mode '1') PIL Image suitable for thermal printing.
        """
        method = method.lower().strip()
        logger.info(f"[ImageProcessor] Applying dithering: {method}")

        if method == DitheringMethod.FLOYD_STEINBERG:
            return self._floyd_steinberg(img)
        elif method == DitheringMethod.THRESHOLD:
            return self._threshold(img)
        elif method == DitheringMethod.NONE:
            return self._no_dither(img)
        elif method == DitheringMethod.ATKINSON:
            return self._atkinson_dither(img)
        else:
            logger.warning(f"[ImageProcessor] Unknown method '{method}', falling back to Floyd-Steinberg")
            return self._floyd_steinberg(img)

    def _floyd_steinberg(self, img: Image.Image) -> Image.Image:
        """Floyd-Steinberg error-diffusion dithering (PIL built-in, fast)."""
        return img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

    def _threshold(self, img: Image.Image) -> Image.Image:
        """Simple threshold at 128 — no dithering."""
        return img.point(lambda x: 255 if x > 128 else 0, '1')

    def _no_dither(self, img: Image.Image) -> Image.Image:
        """Convert to 1-bit without dithering (same as threshold)."""
        return img.convert('1', dither=Image.Dither.NONE)
    
    def _atkinson_dither(self, img: Image.Image) -> Image.Image:
        """
        Apply Atkinson dithering (used in early Macintosh).
        Produces lighter images with less contrast than Floyd-Steinberg.
        
        Args:
            img: Grayscale PIL Image
            
        Returns:
            PIL Image in mode '1'
        """
        pixels = list(img.getdata())
        width, height = img.size
        
        # Create mutable pixel array
        pixel_array = [[pixels[y * width + x] for x in range(width)] for y in range(height)]
        
        for y in range(height):
            for x in range(width):
                old_pixel = pixel_array[y][x]
                new_pixel = 255 if old_pixel > 127 else 0
                pixel_array[y][x] = new_pixel
                
                error = (old_pixel - new_pixel) // 8  # Divide by 8 for Atkinson
                
                # Distribute error to neighboring pixels
                if x + 1 < width:
                    pixel_array[y][x + 1] = min(255, max(0, pixel_array[y][x + 1] + error))
                if x + 2 < width:
                    pixel_array[y][x + 2] = min(255, max(0, pixel_array[y][x + 2] + error))
                if y + 1 < height:
                    if x > 0:
                        pixel_array[y + 1][x - 1] = min(255, max(0, pixel_array[y + 1][x - 1] + error))
                    pixel_array[y + 1][x] = min(255, max(0, pixel_array[y + 1][x] + error))
                    if x + 1 < width:
                        pixel_array[y + 1][x + 1] = min(255, max(0, pixel_array[y + 1][x + 1] + error))
                if y + 2 < height:
                    pixel_array[y + 2][x] = min(255, max(0, pixel_array[y + 2][x] + error))
        
        # Convert back to image
        dithered_pixels = [pixel_array[y][x] for y in range(height) for x in range(width)]
        dithered_img = Image.new('L', (width, height))
        dithered_img.putdata(dithered_pixels)
        
        return dithered_img.convert('1', dither=Image.Dither.NONE)
    
