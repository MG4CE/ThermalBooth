#!/usr/bin/env python3
"""
RPi Camera Module 3 – Preview & Capture
========================================
- 800×600 live preview via Pygame
- Continuous autofocus, auto white balance, ISP noise reduction & sharpening
- High-res 3500×2550 capture saved as JPEG or PNG

Dependencies (install on Raspberry Pi OS Bookworm+):
    sudo apt update
    sudo apt install -y python3-picamera2 python3-opencv
"""

import sys
import time
import signal
import threading
import cv2
import pygame
from datetime import datetime

try:
    from picamera2 import Picamera2
except ImportError:
    print("ERROR: picamera2 is required.  Install with:")
    print("  sudo apt install python3-picamera2")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PREVIEW_SIZE = (800, 600)
CAPTURE_SIZE = (3500, 2550)
JPEG_QUALITY = 92             # 90-95 is visually lossless; much smaller than PNG
TARGET_FPS = 24



# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  RPi Camera Module 3 – Preview & Capture")
    print("  Preview : 800×600   |   Capture : 3500×2550")
    print("  Press 'c' capture | 'd' debug | 'f' format | 'q' / ESC quit")
    print("=" * 60)

    # --- Camera setup ---
    picam2 = Picamera2()

    # Preview stream = 800×600, using 2×2 binned sensor mode (2304×1296)
    # for fast readout while preserving the full sensor FOV.
    # Captures switch to full resolution via switch_mode_and_capture_array.
    config = picam2.create_preview_configuration(
        main={"size": PREVIEW_SIZE, "format": "RGB888"},
        raw={"size": (2304, 1296)},
    )
    picam2.configure(config)

    picam2.set_controls({
        "AfMode": 2,               # Continuous AF
        "AfSpeed": 1,              # Fast AF
        "AeMeteringMode": 0,       # Centre-weighted
        "AeExposureMode": 0,       # Normal
        "AwbMode": 0,              # Auto WB
        "Brightness": 0.1,         # Slight brightness lift
        "Contrast": 1.1,           # Slight contrast lift
        "NoiseReductionMode": 2,   # High-quality denoise (ISP)
        "Sharpness": 1.5,          # In-camera sharpening
    })

    picam2.start()
    time.sleep(1)  # Let AE / AF settle

    # --- Pygame display setup (works without GTK/highgui) ---
    pygame.init()
    screen = pygame.display.set_mode(PREVIEW_SIZE)
    pygame.display.set_caption("RPi Camera – Preview (800x600)")

    clock = pygame.time.Clock()
    frame_count = 0
    capture_count = 0
    debug_mode = False
    save_png = False  # Toggle with 'f': False = JPEG, True = PNG

    # Graceful exit on Ctrl-C
    running = True

    def _sigint(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _sigint)

    print("\nCamera started – opening preview window …\n")

    while running:
        # picamera2 "RGB888" = BGR byte order in memory on ARM (DRM convention)
        frame = picam2.capture_array("main")  # actually BGR in memory

        # --- Debug overlays (only when enabled) ---
        if debug_mode:
            cv2.putText(frame, f"FPS: {clock.get_fps():.0f}",
                         (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, "'c' capture | 'd' debug | 'f' format | 'q' quit",
                         (10, PREVIEW_SIZE[1] - 15),
                         cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        # --- Display via pygame (no GTK needed) ---
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        surf = pygame.image.frombuffer(frame_rgb.tobytes(), PREVIEW_SIZE, "RGB")
        screen.blit(surf, (0, 0))
        pygame.display.flip()

        key_pressed = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False
                elif event.key == pygame.K_c:
                    key_pressed = "c"
                elif event.key == pygame.K_d:
                    debug_mode = not debug_mode
                    print(f"  Debug mode: {'ON' if debug_mode else 'OFF'}")
                elif event.key == pygame.K_f:
                    save_png = not save_png
                    print(f"  Save format: {'PNG' if save_png else 'JPEG'}")

        if not running:
            break
        elif key_pressed == "c":
            # --- High-res capture ---
            capture_count += 1
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "png" if save_png else "jpg"
            capture_path = f"capture_{ts}.{ext}"

            print(f"\n📸  Capturing high-res image #{capture_count} …")

            # Fast mode-switch capture: switches to still config,
            # grabs one frame, then auto-returns to preview config.
            still_config = picam2.create_still_configuration(
                main={"size": CAPTURE_SIZE, "format": "RGB888"},
            )
            still = picam2.switch_mode_and_capture_array(still_config)

            # Save in a background thread so preview resumes instantly.
            def _save(path, img, use_png):
                if use_png:
                    cv2.imwrite(path, img)
                else:
                    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                print(f"  Capture saved → {path}")

            threading.Thread(target=_save, args=(capture_path, still, save_png), daemon=True).start()
            print("  Capture taken, saving in background.")

        frame_count += 1
        clock.tick(TARGET_FPS)

    # --- Cleanup ---
    pygame.quit()
    picam2.stop()
    picam2.close()
    print("\nCamera closed. Goodbye!")


if __name__ == "__main__":
    main()
