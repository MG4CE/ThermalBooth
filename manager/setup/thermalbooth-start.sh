#!/usr/bin/env bash
# =========================================================================
# thermalbooth-start.sh — Launch wrapper for ThermalBooth v2.
#
# When run as a systemd *user* service, all desktop environment variables
# (WAYLAND_DISPLAY, XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS, etc.) are
# inherited automatically — no detection needed.
# =========================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python3"

echo "[thermalbooth-start] User=$(whoami) UID=$(id -u)"
echo "[thermalbooth-start] ProjectDir=${PROJECT_DIR}"
echo "[thermalbooth-start] VenvPython=${VENV_PYTHON}"
echo "[thermalbooth-start] WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} DISPLAY=${DISPLAY:-} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}"

# ---- Validate venv python exists ----
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "[thermalbooth-start] ERROR: venv python not found at ${VENV_PYTHON}"
    echo "[thermalbooth-start] Run: bash ${PROJECT_DIR}/install.sh"
    exit 1
fi

# ---- Wait for compositor (up to 30s) ----
# User services with default.target may start before the compositor is ready.
XDG_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
MAX_WAIT=30
WAITED=0
while [[ $WAITED -lt $MAX_WAIT ]]; do
    # Check for Wayland socket
    for sock in "$XDG_DIR"/wayland-*; do
        if [[ -S "$sock" ]] 2>/dev/null; then
            export WAYLAND_DISPLAY="$(basename "$sock")"
            echo "[thermalbooth-start] Compositor ready: WAYLAND_DISPLAY=$WAYLAND_DISPLAY (after ${WAITED}s)"
            break 2
        fi
    done 2>/dev/null
    # Check for X11
    if [[ -n "${DISPLAY:-}" ]]; then
        echo "[thermalbooth-start] X11 session ready: DISPLAY=$DISPLAY (after ${WAITED}s)"
        break
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done
if [[ $WAITED -ge $MAX_WAIT ]]; then
    echo "[thermalbooth-start] WARNING: No compositor found after ${MAX_WAIT}s — falling back to DRM"
fi

# ---- Wayland EGL workaround ----
# picamera2's QTGL preview calls eglGetDisplay(EGL_DEFAULT_DISPLAY) which
# segfaults on VC4 under Wayland.  Force software EGL for the preview window;
# camera capture stays fully hardware-accelerated via libcamera/ISP.
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM=wayland
    export LIBGL_ALWAYS_SOFTWARE=1
fi

# ---- Launch the booth ----
cd "$PROJECT_DIR"
echo "[thermalbooth-start] Launching: $VENV_PYTHON ${PROJECT_DIR}/main.py"
exec "$VENV_PYTHON" "${PROJECT_DIR}/main.py"
