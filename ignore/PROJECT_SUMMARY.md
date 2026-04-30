# ThermalBooth v2 — Project Summary

> **Last updated:** February 6, 2026
> **Purpose:** Reference document for AI agents and future developers working on this codebase.

---

## Overview

A Raspberry Pi camera photo booth that displays a fullscreen camera preview on a 600×1024 screen, captures photos on button press (GPIO or keyboard), processes them (enhance → dither) for thermal printing, and prints via a USB ESC/POS thermal printer.

---

## Directory Structure

```
ThermalBooth_v2/
├── config.json              # All application settings (42 lines)
├── main.py                  # Entry point & state machine (218 lines)
├── requirements_rpi.txt     # RPi Python dependencies (10 lines)
├── camera/
│   ├── __init__.py
│   └── pi_cam_module_3.py   # Picamera2 DRM/KMS preview + capture (203 lines)
├── display/
│   ├── __init__.py
│   └── overlay.py           # GPU-composited countdown/flash (120 lines)
├── image/
│   ├── __init__.py
│   ├── handler.py           # Enhancement + processing pipeline (175 lines)
│   └── processor.py         # 6 dithering algorithms (173 lines)
├── input/
│   ├── __init__.py
│   └── gpio.py              # Single GPIO shutter button (88 lines)
└── printer/
    ├── __init__.py
    ├── bluetooth.py          # BT scan/pair/RFCOMM (772 lines) — UNUSED, kept for future
    ├── escpos_printer.py     # ESC/POS USB protocol (235 lines)
    ├── exceptions.py         # Custom exception hierarchy (49 lines)
    ├── manager.py            # Printer facade, USB-only (148 lines)
    ├── startsp_printer.py    # Star TSP raster protocol (392 lines) — UNUSED, kept for future
    └── usb.py                # USB device detection (227 lines)
```

**Total:** ~2,852 lines across 19 files.

---

## Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      main.py — Booth                            │
│   State Machine: IDLE → COUNTDOWN → CAPTURE → PROCESS → PRINT  │
│                                                                 │
│   Event Loop: evdev keyboard / GPIO button / terminal stdin     │
│   _trigger() → spawns _capture_cycle() in background thread     │
└───────┬──────────┬──────────┬───────────┬───────────┬───────────┘
        │          │          │           │           │
   ┌────▼────┐ ┌───▼───┐ ┌───▼───┐  ┌────▼────┐ ┌───▼─────┐
   │ Camera  │ │Overlay│ │ Image │  │ Printer │ │  GPIO   │
   │ Preview │ │Display│ │Handler│  │ Manager │ │ Handler │
   │(DRM/KMS)│ │ (GPU) │ │(PIL)  │  │(ESC/POS)│ │(gpiozero)│
   └─────────┘ └───────┘ └───────┘  └─────────┘ └─────────┘
```

### Capture Cycle (one photo):

1. **Trigger** — GPIO button or Spacebar fires `_trigger()` in `main.py`
2. **COUNTDOWN** — `display/overlay.py` renders 3-2-1 as RGBA NumPy arrays → pushed to GPU via `set_overlay()`
3. **CAPTURE** — White flash overlay → `camera/pi_cam_module_3.py` calls `switch_mode_and_capture_file()` → full-res JPEG saved to `uploads/`
4. **PROCESS** — `image/handler.py` runs: EXIF fix → upscale (LANCZOS) → sharpen → contrast → brightness → greyscale → dither → resize to `print_width` → save PNG to `processed/`
5. **PRINT** — `printer/manager.py` → `escpos_printer.py` → loads 1-bit image → `printer.image()` → feed → cut
6. **Return to IDLE**

---

## Key Design Decisions

### Performance (critical requirement)
- **DRM/KMS preview**: Camera frames go GPU → display directly. Python never touches preview frames.
- **Native libcamera controls**: Brightness, contrast, saturation, denoise are ISP-level. No per-frame Python manipulation.
- **GPU-composited overlays**: Countdown/flash are RGBA buffers blended by hardware at vsync. No Pygame/SDL.
- **Background capture thread**: `_capture_cycle()` runs in a daemon thread so the input loop and preview aren't blocked.
- **`switch_mode_and_capture_file()`**: Avoids preview freeze during capture — DRM holds last buffer while still config is active.

### Printer
- **USB ESC/POS only** in `manager.py`. Bluetooth (`bluetooth.py`) and StarTSP (`startsp_printer.py`) are present but **not wired in** — kept for potential future use.
- Auto-detect scans 5 common vendor/product IDs.
- Falls back to **simulation mode** if no printer found (logs prints instead).

### Image Processing
- OV5647 camera (~5MP) produces low-quality images. Enhancement pipeline upscales, sharpens, and boosts contrast before dithering.
- 6 dithering methods available; default is Floyd-Steinberg (uses PIL built-in, fast).
- Final image resized to `print_width` (384px for 58mm paper, 576px for 80mm).
- **Testing mode**: Set `testing_mode: true` or `save_debug_images: true` to save `{id}_raw.jpg`, `{id}_enhanced.jpg`, `{id}_dithered.png` to `debug/`.

---

## Config Reference (`config.json`)

| Section | Key | Default | Notes |
|---------|-----|---------|-------|
| `printer` | `protocol` | `"escpos"` | Only `"escpos"` is wired in currently |
| | `type` | `"usb"` | Only USB supported currently |
| | `auto_detect` | `true` | Scans common vendor/product IDs |
| | `retry_attempts` | `3` | Print retry count |
| | `print_width` | `384` | Final image width in px (384=58mm, 576=80mm @ 203 DPI) |
| | `bottom_padding` | `80` | Whitespace at bottom of raster (Star TSP only) |
| `gpio` | `pin` | `22` | BCM pin for shutter button (single pin, not array) |
| | `bounce_time` | `250` | Debounce in milliseconds |
| `camera` | `width` / `height` | `600` / `1024` | Preview resolution (must match display) |
| | `framerate` | `24` | Preview FPS |
| | `saturation` | `0.0` | 0 = greyscale preview |
| | `brightness` | `0.1` | Slight boost (libcamera range: -1.0 to 1.0) |
| | `denoise` | `"cdn_off"` | `cdn_off` / `cdn_fast` / `cdn_hq` |
| | `capture_width/height` | `2592×1944` | Full-res still (OV5647 native) |
| `display` | `countdown_seconds` | `3` | 3-2-1 countdown |
| | `flash_duration_ms` | `150` | White flash length |
| | `font_size` | `200` | Countdown digit size (pixels) |
| `image_settings` | `dither_method` | `"floyd_steinberg"` | Default dithering algorithm |
| | `enhancement.sharpness` | `1.8` | PIL ImageEnhance multiplier |
| | `enhancement.contrast` | `1.4` | PIL ImageEnhance multiplier |
| | `enhancement.brightness` | `1.1` | PIL ImageEnhance multiplier |
| | `enhancement.upscale_factor` | `1.5` | LANCZOS upscale before dithering |
| _(root)_ | `testing_mode` | `false` | Save debug images at each processing stage |
| | `save_debug_images` | `false` | Also saves debug images |
| | `debug_dir` | `"debug"` | Output directory for debug images |

---

## Known Issues & Technical Debt

### Bugs to Fix
1. **Race condition in `_trigger()`** (`main.py`) — `_busy` flag is checked and set without a lock. Two near-simultaneous triggers could both pass. → Use `threading.Lock` or `threading.Event`.
2. **`_connect_usb()` signature mismatch** (`printer/manager.py` original had this, now fixed) — was accepting 0 args but called with 3.
3. **Atkinson dithering is extremely slow** (`image/processor.py`) — Pure Python pixel-by-pixel loops. On a ~3888×2916 image (after 1.5× upscale), this takes minutes on RPi. → Needs NumPy vectorization or a pre-resize step.
4. **`threshold` and `none` dithering are identical** (`image/processor.py`) — Both call `img.convert('1', dither=Image.Dither.NONE)`. The `threshold` docstring claims a 128 cutoff but doesn't implement one.

### Dead Code
6. **`bluetooth.py` (772 lines)** and **`startsp_printer.py` (392 lines)** — ~1,164 lines of unused code. Not imported by `manager.py`. Kept for potential future Bluetooth printer support.

### Missing Features
7. **No disk cleanup** — Photos accumulate in `uploads/` and `processed/` indefinitely. SD card will fill up.
8. **No unit tests** — No `tests/` directory exists.
9. **No user-facing error display** — If print fails, only logged. User sees "Printing…" then it just returns to idle.
10. **No systemd service file** — No auto-start on boot.

---

## Dependencies (`requirements_rpi.txt`)

| Package | Used By |
|---------|---------|
| `python-escpos` | `printer/escpos_printer.py`, `printer/usb.py` |
| `gpiozero` | `input/gpio.py` |
| `RPi.GPIO` | Backend for gpiozero |
| `lgpio` | Alternative GPIO backend |
| `pyusb` | USB device access (backend for python-escpos) |
| `picamera2` | `camera/pi_cam_module_3.py` |
| `numpy` | `display/overlay.py` (RGBA overlay buffers) |
| `Pillow` | `image/handler.py`, `image/processor.py`, `display/overlay.py` |
| `evdev` | `main.py` (keyboard input without X11) |

**Not in requirements but used**: `libcamera` (comes with `picamera2` on RPi OS).
**In code but not in requirements**: `pyserial` (used by `bluetooth.py` — currently dead code).

---

## How to Run

```bash
cd /home/maged/Desktop/Projects/ThermalBooth_v2
pip install -r requirements_rpi.txt
python main.py
```

- **Spacebar** — Trigger capture
- **GPIO pin 22** — Trigger capture (physical button)
- **Escape** — Quit

---

## Module Import Map

```python
# main.py imports:
from camera.pi_cam_module_3 import Camera
from display.overlay import Overlay
from image.handler import ImageHandler
from printer.manager import PrinterManager
from input.gpio import GPIOHandler

# printer/manager.py imports:
from .escpos_printer import ESCPOSPrinter
from .exceptions import PrinterError, InvalidConfigurationError

# printer/escpos_printer.py imports:
from .usb import USBConnection
from .exceptions import PrinterConnectionError

# image/handler.py imports:
from image.processor import ImageProcessor, DitheringMethod

# NOT imported anywhere (dead code):
# printer/bluetooth.py
# printer/startsp_printer.py
```

---

## GPIO Wiring

```
RPi GPIO Pin 22 (BCM) ──── Button ──── GND
                         (normally open, internal pull-up)
```

---

## Historical Notes

- **v1 → v2 migration**: The original design had multi-button support (`gpio.pins: [22]` array) and a Flask web upload interface (`save_uploaded_image()` accepting file objects). v2 simplified to a single shutter button and direct file path processing.
- **Bluetooth/StarTSP**: Was designed for Star TSP100 receipt printers over Bluetooth RFCOMM. Removed from the active code path in v2 but source files retained in `printer/` for potential reactivation.
- **Pygame was considered and rejected**: To avoid preview frame drops, the architecture uses Picamera2's native DRM preview + `set_overlay()` instead of blitting camera frames onto a Pygame surface.
