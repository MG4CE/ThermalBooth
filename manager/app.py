#!/usr/bin/env python3
"""
ThermalBooth Manager — Web-based control panel for ThermalBooth.
Provides start/stop/restart controls, config editing, and log viewing.
Runs on port 5050 by default.
"""

import json
import os
import subprocess
import sys
import tempfile

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
MEDIA_DIR = os.path.join(PROJECT_DIR, "media")
SERVICE_NAME = "thermalbooth"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}

# ---------------------------------------------------------------------------
# Config field metadata — drives the dynamic form in the UI
# ---------------------------------------------------------------------------
CONFIG_SCHEMA = {
    "printer": {
        "_label": "Printer",
        "vendor_id": {"type": "int", "label": "Vendor ID", "min": 0},
        "product_id": {"type": "int", "label": "Product ID", "min": 0},
        "auto_detect": {"type": "bool", "label": "Auto Detect"},
        "retry_attempts": {"type": "int", "label": "Retry Attempts", "min": 1, "max": 10},
        "line_spacing": {"type": "int", "label": "Line Spacing", "min": 0, "max": 100},
        "print_width": {"type": "int", "label": "Print Width (px)", "min": 100, "max": 1000},
        "heat_time": {"type": "int", "label": "Heat Time (×10µs)", "min": 5, "max": 40},
        "max_dots": {"type": "int", "label": "Max Heating Dots", "min": 0, "max": 30},
    },
    "gpio": {
        "_label": "GPIO",
        "pin": {"type": "int", "label": "BCM Pin", "min": 0, "max": 27},
        "bounce_time": {"type": "int", "label": "Bounce Time (ms)", "min": 50, "max": 1000},
        "pull_up_down": {
            "type": "enum",
            "label": "Pull Up/Down",
            "options": ["pull_up", "pull_down"],
        },
    },
    "camera": {
        "_label": "Camera",
        "width": {"type": "int", "label": "Preview Width", "min": 320, "max": 1920},
        "height": {"type": "int", "label": "Preview Height", "min": 240, "max": 1080},
        "framerate": {"type": "int", "label": "Framerate", "min": 1, "max": 60},
        "color_preview": {"type": "bool", "label": "Color Preview"},
        "brightness": {"type": "float", "label": "Brightness", "min": -1.0, "max": 1.0, "step": 0.05},
        "ae_metering_mode": {
            "type": "enum",
            "label": "AE Metering Mode",
            "options": ["spot", "centreweighted", "matrix"],
        },
        "ae_exposure_mode": {
            "type": "enum",
            "label": "AE Exposure Mode",
            "options": ["normal", "short", "long"],
        },
        "exposure_value": {"type": "float", "label": "Exposure Value (EV)", "min": -8.0, "max": 8.0, "step": 0.1},
        "contrast": {"type": "float", "label": "Contrast", "min": 0.0, "max": 5.0, "step": 0.05},
        "sharpness": {"type": "float", "label": "Sharpness", "min": 0.0, "max": 5.0, "step": 0.1},
        "autofocus": {"type": "bool", "label": "Autofocus"},
        "af_range": {
            "type": "enum",
            "label": "AF Range",
            "options": ["normal", "macro", "full"],
        },
        "denoise": {
            "type": "enum",
            "label": "Denoise Mode",
            "options": ["off", "cdn_off", "cdn_fast", "cdn_hq"],
        },
        "raw_width": {"type": "int", "label": "Raw Width", "min": 640, "max": 4608},
        "raw_height": {"type": "int", "label": "Raw Height", "min": 480, "max": 2592},
        "capture_width": {"type": "int", "label": "Capture Width", "min": 640, "max": 4608},
        "capture_height": {"type": "int", "label": "Capture Height", "min": 480, "max": 2592},
        "jpeg_quality": {"type": "int", "label": "JPEG Quality", "min": 1, "max": 100},
    },
    "display": {
        "_label": "Display",
        "width": {"type": "int", "label": "Width", "min": 320, "max": 1920},
        "height": {"type": "int", "label": "Height", "min": 240, "max": 1080},
        "fullscreen": {"type": "bool", "label": "Fullscreen"},
        "countdown_seconds": {"type": "int", "label": "Countdown Seconds", "min": 1, "max": 10},
        "countdown_color": {"type": "bool", "label": "Countdown Color"},
        "flash_duration_ms": {"type": "int", "label": "Flash Duration (ms)", "min": 0, "max": 1000},
        "result_display_seconds": {"type": "int", "label": "Result Display (s)", "min": 1, "max": 30},
        "font_size": {"type": "int", "label": "Font Size", "min": 10, "max": 500},
        "show_status_messages": {"type": "bool", "label": "Show Status Messages"},
    },
    "image_settings": {
        "_label": "Image Settings",
        "dither_method": {
            "type": "enum",
            "label": "Dither Method",
            "options": ["atkinson", "floyd_steinberg", "threshold", "none"],
        },
        "header_image": {"type": "upload", "label": "Header Image", "upload_key": "header"},
        "header_max_height": {"type": "int", "label": "Header Max Height", "min": 0, "max": 1000},
        "header_gap": {"type": "int", "label": "Header Gap (px)", "min": 0, "max": 200},
        "footer_image": {"type": "upload", "label": "Footer Image", "upload_key": "footer"},
        "footer_max_height": {"type": "int", "label": "Footer Max Height", "min": 0, "max": 1000},
        "footer_gap": {"type": "int", "label": "Footer Gap (px)", "min": 0, "max": 200},
    },
    "_root": {
        "_label": "General",
        "save_debug_images": {"type": "bool", "label": "Save Debug Images"},
        "debug_dir": {"type": "string", "label": "Debug Directory"},
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_config() -> dict:
    """Read and return the current config.json."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def write_config(data: dict) -> None:
    """Atomically write config.json (write to tmp, then os.replace)."""
    dir_name = os.path.dirname(CONFIG_PATH)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        # Clean up tmp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def configs_equal(a: dict, b: dict) -> bool:
    """Deep-compare two config dicts, ignoring key order and whitespace."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _user_env() -> dict:
    """Return env dict with XDG_RUNTIME_DIR and DBUS set for --user commands."""
    env = os.environ.copy()
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def systemctl(*args: str) -> subprocess.CompletedProcess:
    """Run a systemctl --user command (no sudo needed for user services)."""
    cmd = ["systemctl", "--user"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=_user_env())


def get_service_status() -> dict:
    """Get the current status of the thermalbooth service."""
    result = systemctl("is-active", SERVICE_NAME)
    active_state = result.stdout.strip()

    info = {"state": active_state, "pid": None, "uptime": None}

    # Get extra details if active
    show_result = systemctl(
        "show", SERVICE_NAME,
        "--property=ActiveState,SubState,MainPID,ActiveEnterTimestamp",
    )
    if show_result.returncode == 0:
        for line in show_result.stdout.strip().splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                if key == "MainPID" and val != "0":
                    info["pid"] = int(val)
                elif key == "ActiveEnterTimestamp" and val:
                    info["uptime"] = val
                elif key == "SubState":
                    info["sub_state"] = val

    return info


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)
os.makedirs(MEDIA_DIR, exist_ok=True)


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Return current booth service status as JSON."""
    try:
        status = get_service_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"state": "unknown", "error": str(e)}), 500


@app.route("/api/config")
def api_config():
    """Return the current config and schema."""
    try:
        config = read_config()
        return jsonify({"config": config, "schema": CONFIG_SCHEMA})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def api_config_save():
    """
    Save config if changed. Restart booth service if running and config changed.
    Returns: {changed: bool, restarted: bool}
    """
    try:
        new_config = request.get_json()
        if new_config is None:
            return jsonify({"error": "Invalid JSON body"}), 400

        current_config = read_config()

        if configs_equal(current_config, new_config):
            return jsonify({"changed": False, "restarted": False})

        write_config(new_config)

        # Check if the booth is running, restart if so
        status = get_service_status()
        restarted = False
        if status["state"] == "active":
            systemctl("restart", SERVICE_NAME)
            restarted = True

        return jsonify({"changed": True, "restarted": restarted})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start the booth service."""
    try:
        result = systemctl("start", SERVICE_NAME)
        ok = result.returncode == 0
        return jsonify({"success": ok, "message": result.stderr.strip() if not ok else "Started"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop the booth service."""
    try:
        result = systemctl("stop", SERVICE_NAME)
        ok = result.returncode == 0
        return jsonify({"success": ok, "message": result.stderr.strip() if not ok else "Stopped"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """Restart the booth service."""
    try:
        result = systemctl("restart", SERVICE_NAME)
        ok = result.returncode == 0
        return jsonify({"success": ok, "message": result.stderr.strip() if not ok else "Restarted"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/upload/<image_type>", methods=["POST"])
def api_upload(image_type):
    """Upload a header or footer image. Replaces any previous file."""
    if image_type not in ("header", "footer"):
        return jsonify({"error": "Invalid image type"}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"File type {ext} not allowed"}), 400

    # Remove any existing file for this image type
    for existing in os.listdir(MEDIA_DIR):
        if existing.startswith(f"{image_type}."):
            os.remove(os.path.join(MEDIA_DIR, existing))

    filename = f"{image_type}{ext}"
    dest = os.path.join(MEDIA_DIR, filename)
    f.save(dest)

    # Update config to point to the new file
    config = read_config()
    config.setdefault("image_settings", {})
    config["image_settings"][f"{image_type}_image"] = dest
    write_config(config)

    # Restart booth service so ImageHandler picks up the new image
    restarted = False
    status = get_service_status()
    if status["state"] == "active":
        systemctl("restart", SERVICE_NAME)
        restarted = True

    return jsonify({"success": True, "path": dest, "filename": filename, "restarted": restarted})


@app.route("/api/media/<image_type>")
def api_media(image_type):
    """Serve the current header or footer image for preview."""
    if image_type not in ("header", "footer"):
        return jsonify({"error": "Invalid image type"}), 404

    for existing in os.listdir(MEDIA_DIR):
        if existing.startswith(f"{image_type}."):
            return send_from_directory(MEDIA_DIR, existing)

    return "", 404


@app.route("/api/logs")
def api_logs():
    """Return the last N lines of booth service journal logs."""
    n = request.args.get("n", 80, type=int)
    n = min(n, 500)  # cap

    try:
        # Use _SYSTEMD_USER_UNIT= match — doesn't need D-Bus, works
        # reliably from within a sibling user service.
        result = subprocess.run(
            [
                "journalctl",
                f"_SYSTEMD_USER_UNIT={SERVICE_NAME}.service",
                "--no-pager", "-n", str(n),
            ],
            capture_output=True, text=True, timeout=10,
        )
        logs = result.stdout
        # Fallback: if empty, try --user (may work if DBUS is available)
        if not logs.strip() or "No entries" in logs:
            result2 = subprocess.run(
                ["journalctl", "--user", "-u", SERVICE_NAME, "--no-pager", "-n", str(n)],
                capture_output=True, text=True, timeout=10, env=_user_env(),
            )
            if result2.stdout.strip():
                logs = result2.stdout
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"logs": f"Error fetching logs: {e}"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"ThermalBooth Manager starting on http://0.0.0.0:5050")
    print(f"Config path: {CONFIG_PATH}")
    print(f"Project dir: {PROJECT_DIR}")

    # Auto-start the booth service
    try:
        status = get_service_status()
        if status["state"] != "active":
            print("Auto-starting thermalbooth service...")
            result = systemctl("start", SERVICE_NAME)
            if result.returncode == 0:
                print("thermalbooth service started successfully")
            else:
                print(f"Failed to start thermalbooth: {result.stderr.strip()}")
        else:
            print("thermalbooth service already running")
    except Exception as e:
        print(f"Could not auto-start thermalbooth: {e}")

    app.run(host="0.0.0.0", port=5050, debug=False)
