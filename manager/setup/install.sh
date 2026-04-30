#!/usr/bin/env bash
# =========================================================================
# install.sh — Sets up systemd user services and user groups for
# ThermalBooth and its web manager.
#
# Usage:
#   sudo bash install.sh            # Install
#   sudo bash install.sh uninstall  # Uninstall
# =========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python3"
BOOTH_USER="${SUDO_USER:-$(whoami)}"
BOOTH_HOME="$(eval echo "~${BOOTH_USER}")"
BOOTH_UID="$(id -u "$BOOTH_USER")"
USER_SERVICE_DIR="${BOOTH_HOME}/.config/systemd/user"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }

# ---- Root check ----
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo bash install.sh)"
    exit 1
fi

# Helper: run a command as the booth user (preserving XDG_RUNTIME_DIR)
run_as_user() {
    sudo -u "$BOOTH_USER" XDG_RUNTIME_DIR="/run/user/${BOOTH_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${BOOTH_UID}/bus" "$@"
}

# =====================================================================
# Uninstall
# =====================================================================
if [[ "${1:-}" == "uninstall" ]]; then
    echo ""
    echo "Uninstalling ThermalBooth services..."
    echo ""

    # Stop services
    run_as_user systemctl --user stop thermalbooth.service 2>/dev/null && info "Stopped thermalbooth" || true
    run_as_user systemctl --user stop thermalbooth-manager.service 2>/dev/null && info "Stopped thermalbooth-manager" || true

    # Disable services
    run_as_user systemctl --user disable thermalbooth.service 2>/dev/null && info "Disabled thermalbooth" || true
    run_as_user systemctl --user disable thermalbooth-manager.service 2>/dev/null && info "Disabled thermalbooth-manager" || true

    # Remove service files
    for svc in thermalbooth.service thermalbooth-manager.service; do
        if [[ -f "${USER_SERVICE_DIR}/${svc}" ]]; then
            rm -f "${USER_SERVICE_DIR}/${svc}"
            info "Removed ${USER_SERVICE_DIR}/${svc}"
        fi
    done

    # Reload user daemon
    run_as_user systemctl --user daemon-reload 2>/dev/null || true
    info "Reloaded user systemd daemon"

    # Disable lingering (optional — keeps it if user wants it)
    # loginctl disable-linger "$BOOTH_USER" 2>/dev/null && info "Disabled linger for $BOOTH_USER" || true

    echo ""
    echo "========================================================="
    echo "  ThermalBooth services uninstalled."
    echo "========================================================="
    echo ""
    echo "  Note: User groups and the venv were NOT removed."
    echo "  To also remove the venv:"
    echo "    rm -rf ${PROJECT_DIR}/venv"
    echo ""
    exit 0
fi

# =====================================================================
# Install
# =====================================================================

# Check venv exists
if [[ ! -x "$VENV_PYTHON" ]]; then
    error "Virtual environment not found at ${PROJECT_DIR}/venv/"
    echo "  Run first:  bash ${PROJECT_DIR}/install.sh install"
    exit 1
fi

# Check Flask is installed in venv
if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
    error "Flask not found in venv."
    echo "  Run first:  bash ${PROJECT_DIR}/install.sh install"
    exit 1
fi

info "Preflight checks passed"

# ---- Enable persistent journal storage ----
# RPi OS defaults to volatile (RAM) journal — user service logs are lost.
# Creating /var/log/journal/ enables persistent storage so logs survive reboots
# and journalctl can find them.
if [[ ! -d /var/log/journal ]]; then
    mkdir -p /var/log/journal
    systemd-tmpfiles --create --prefix /var/log/journal
    systemctl restart systemd-journald
    info "Enabled persistent journal storage"
else
    info "Persistent journal storage already enabled"
fi

# ---- Make start script executable ----
chmod +x "${SCRIPT_DIR}/thermalbooth-start.sh"
info "Made thermalbooth-start.sh executable"

# ---- Create user service directory ----
mkdir -p "$USER_SERVICE_DIR"
chown "${BOOTH_USER}:${BOOTH_USER}" "$USER_SERVICE_DIR"
info "Ensured ${USER_SERVICE_DIR} exists"

# ---- Copy user service files (with path substitution) ----
for svc in thermalbooth.service thermalbooth-manager.service; do
    sed -e "s|__USER__|${BOOTH_USER}|g" \
        -e "s|__HOME__|${BOOTH_HOME}|g" \
        -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
        "${SCRIPT_DIR}/${svc}" > "${USER_SERVICE_DIR}/${svc}"
    chown "${BOOTH_USER}:${BOOTH_USER}" "${USER_SERVICE_DIR}/${svc}"
done
info "Installed user service files to ${USER_SERVICE_DIR}"

# ---- Add user to required hardware groups ----
REQUIRED_GROUPS=(video gpio input lp render)
for grp in "${REQUIRED_GROUPS[@]}"; do
    if getent group "$grp" >/dev/null 2>&1; then
        if ! id -nG "$BOOTH_USER" | grep -qw "$grp"; then
            usermod -aG "$grp" "$BOOTH_USER"
            info "Added $BOOTH_USER to group: $grp"
        fi
    else
        warn "Group '$grp' does not exist on this system — skipping"
    fi
done

# ---- Enable lingering so user services start at boot (before login) ----
loginctl enable-linger "$BOOTH_USER"
info "Enabled linger for ${BOOTH_USER} (services will start at boot)"

# ---- Reload user daemon and enable services ----
run_as_user systemctl --user daemon-reload
info "Reloaded user systemd daemon"

run_as_user systemctl --user enable thermalbooth.service
run_as_user systemctl --user enable thermalbooth-manager.service
info "Enabled both user services"

# ---- Start the web manager now ----
run_as_user systemctl --user start thermalbooth-manager.service
info "Started thermalbooth-manager service"

# ---- Summary ----
echo ""
echo "========================================================="
echo "  ThermalBooth Manager installed successfully!"
echo "========================================================="
echo ""
echo "  Web UI:    http://$(hostname -I | awk '{print $1}'):5050"
echo "             http://$(hostname).local:5050"
echo ""
echo "  Services (user services — no sudo needed):"
echo "    thermalbooth          — photo booth (start via web UI)"
echo "    thermalbooth-manager  — web manager (running now)"
echo ""
echo "  Commands:"
echo "    systemctl --user status thermalbooth"
echo "    systemctl --user status thermalbooth-manager"
echo "    journalctl _SYSTEMD_USER_UNIT=thermalbooth.service -f"
echo "    journalctl _SYSTEMD_USER_UNIT=thermalbooth-manager.service -f"
echo ""
echo "  To uninstall:"
echo "    sudo bash ${PROJECT_DIR}/install.sh uninstall"
echo ""
