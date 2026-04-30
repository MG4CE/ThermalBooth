# ThermalBooth

A Raspberry Pi photo booth that captures photos and prints them instantly on a thermal printer. Mostly vibecoded.

Press a button → 3-2-1 countdown → snapshot → dithered black & white print. That's it.

---

## Hardware

- Raspberry Pi (tested on Pi 4)
- Raspberry Pi Camera Module 3
- Generic 80mm USB thermal printer (ESC/POS)
- A momentary push button wired to GPIO 17 (BCM)
- 7 inch 720p monitor (for live preview)
- 3D printed enclosure (optional, STL included)

---

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url>
cd ThermalBooth
bash install.sh

# 2. Edit config if needed (printer USB IDs, GPIO pin, print width, etc.)
nano config.json

# 3. Run
source venv/bin/activate
python main.py
```

**Controls:** `SPACE` to trigger, `ESC` to quit.

The `install.sh` script also sets up two systemd services:
- `thermalbooth.service` — the photo booth itself (auto-starts on boot)
- `thermalbooth-manager.service` — a web UI at `http://<pi-ip>:5050` for config and controls

---

## Web Manager

If both services are running you don't need to touch `main.py` or the terminal at all. Open `http://<pi-ip>:5050` in a browser and you get:

- **Start / Stop / Restart** the booth service with one click
- **Edit all config settings** through a generated form — saves and auto-restarts the service
- **Upload header/footer images** to print above/below every photo
- **Live log viewer** pulling from the systemd journal

To start the manager manually:

```bash
source venv/bin/activate
python manager/app.py
```

Or let systemd handle it — after `install.sh` both services start on boot and the manager can control the booth service from there.

---

## Configuration

All settings live in `config.json`. Key ones to check:

| Key | Default | Notes |
|-----|---------|-------|
| `printer.print_width` | `576` | `384` = 58mm paper, `576` = 80mm paper |
| `printer.auto_detect` | `true` | Auto-finds common thermal printer USB IDs |
| `gpio.pin` | `17` | BCM GPIO pin for the shutter button |
| `camera.color_preview` | `false` | `true` for colour preview, `false` for B&W |
| `image_settings.dither_method` | `atkinson` | `atkinson`, `floyd_steinberg`, `threshold`, `none` |

---

## 3D Printed Enclosure

An STL file for a printable enclosure is included under the `models/` directory.

---

## Dependencies

```
picamera2, python-escpos, pyusb, gpiozero, RPi.GPIO, lgpio, numpy, Pillow, evdev, flask
```

Installed automatically by `install.sh`.
