"""
Heat Level Test Script
======================
Prints a 200x200 checkerboard pattern 5 times, each with a different
ESC/POS heating-time value stepping from 20 → 100.

ESC 7 (1B 37) parameters:
  n1 = max printing dots (kept at 35 = 0x23)
  n2 = heating time      (varied: 20, 40, 60, 80, 100)
  n3 = heating interval  (kept at 20 = 0x14)

Run from the project root:
  python test_heat_levels.py
"""

import sys
import time
import logging
from PIL import Image

# ── project printer stack ────────────────────────────────────────────────────
from printer.usb import USBConnection
from printer.exceptions import PrinterNotFoundError, USBConnectionError

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def make_checkerboard(size: int = 300, block: int = 3) -> Image.Image:
    """Return a 1-bit PIL image with alternating black/white blocks.

    Args:
        size:  Image width and height in pixels.
        block: Side length of each square block in pixels.
    """
    img = Image.new("1", (size, size))
    pixels = img.load()
    for y in range(size):
        for x in range(size):
            pixels[x, y] = ((x // block) + (y // block)) % 2  # 0 = black, 1 = white
    return img


def set_heat(printer_raw, max_dots: int = 35, heat_time: int = 50, heat_interval: int = 10):
    """
    Send ESC 7 to configure print energy.

    Args:
        printer_raw : callable — the _raw() method of the escpos Usb object
        max_dots    : max heating dots (0–50)
        heat_time   : heating time in 10 µs units (0–50)
        heat_interval: heating interval in 10 µs units (0–30)
    """
    heat_time     = max(5,   min(50, heat_time))
    max_dots      = max(0,   min(30, max_dots))
    heat_interval = max(0,   min(30, heat_interval))
    cmd = bytes([0x1B, 0x37, max_dots, heat_time, heat_interval])
    printer_raw(cmd)
    logger.debug(
        f"ESC 7 → max_dots={max_dots}  heat_time={heat_time}  heat_interval={heat_interval}"
    )


# ── main ─────────────────────────────────────────────────────────────────────

def spam_heat(printer_raw, times: int = 10, heat_time: int = 30, max_dots: int = 5, heat_interval: int = 1):
    """Repeatedly reset the printer and apply heat settings."""
    for _ in range(times):
        printer_raw(b'\x1b\x40')  # ESC @ — reset
        set_heat(printer_raw, max_dots=max_dots, heat_time=heat_time, heat_interval=heat_interval)


def main():
    heat_levels      = [10, 15, 20]   # ESC 7 n2 — heating time (×10 µs)
    max_dots_levels  = [5, 7, 10]   # ESC 7 n1 — max heating dots
    heat_intervals   = [10,12, 15]   # ESC 7 n3 — heating interval (×10 µs)

    # ── connect ──────────────────────────────────────────────────────────────
    logger.info("Connecting to USB printer (auto-detect)…")
    usb = USBConnection(auto_detect=True)
    try:
        usb.connect()
    except (PrinterNotFoundError, USBConnectionError) as exc:
        logger.error(f"Could not connect to printer: {exc}")
        sys.exit(1)

    printer = usb.get_printer()
    logger.info("Printer connected.")

    spam_heat(printer._raw)

    # ── generate checkerboard ─────────────────────────────────────────────────
    checkerboard = make_checkerboard(200)
    logger.info("200×200 checkerboard image generated.")

    total = len(heat_levels) * len(max_dots_levels) * len(heat_intervals)
    count = 0

    # ── print loop ────────────────────────────────────────────────────────────
    for heat in heat_levels:
        for max_dots in max_dots_levels:
            for interval in heat_intervals:
                count += 1
                logger.info(
                    f"[{count}/{total}] heat={heat}  max_dots={max_dots}  interval={interval}…"
                )

                # Initialise printer
                printer._raw(b'\x1b\x40')        # ESC @ — reset

                # Set ESC 7 parameters
                set_heat(printer._raw, max_dots=max_dots, heat_time=heat, heat_interval=interval)

                # Set line spacing
                printer._raw(bytes([0x1B, 0x33, 20]))   # ESC 3 n — line spacing 20

                # Label above the pattern
                printer.set(align='center', bold=True)
                printer.text(f"heat={heat} dots={max_dots} intv={interval}\n")
                printer.set(align='left', bold=False)

                # Print the checkerboard
                printer.image(checkerboard)

                # Gap + cut
                printer._raw(bytes([0x1B, 0x33, 30]))   # restore line spacing
                printer.text('\n')
                time.sleep(0.5)

                logger.info(f"  → done")

                # Cool-down between prints
                if count < total:
                    logger.info("  Cooling down 1 s before next print…")
                    time.sleep(1)
    
    printer.cut()

    logger.info("All heat-level prints finished.")
    usb.disconnect()


if __name__ == "__main__":
    main()
