#!/usr/bin/env bash
# =========================================================================
# install.sh — ThermalBooth Installer
#
# Unified installer for the ThermalBooth project. Manages the Python
# virtual environment, pip dependencies, and systemd service setup.
#
# Usage:
#   bash install.sh install     # Create venv & install pip dependencies
#   bash install.sh services    # Set up systemd services (requires sudo)
#   bash install.sh uninstall   # Remove systemd services (requires sudo)
#   bash install.sh             # Same as: install + services
# =========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
SETUP_DIR="${SCRIPT_DIR}/manager/setup"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }

usage() {
    echo "Usage: bash install.sh [command]"
    echo ""
    echo "Commands:"
    echo "  install     Create venv and install pip dependencies"
    echo "  services    Set up systemd services (requires sudo)"
    echo "  uninstall   Remove systemd services (requires sudo)"
    echo "  help        Show this help message"
    echo ""
    echo "With no command, runs 'install' then 'services'."
}

# =====================================================================
# install — venv + pip dependencies
# =====================================================================
do_install() {
    echo ""
    echo "Setting up Python environment..."
    echo ""

    # ---- Check Python 3 is available ----
    if ! command -v python3 &>/dev/null; then
        error "python3 not found. Please install Python 3."
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version 2>&1)
    info "Found ${PYTHON_VERSION}"

    # ---- Create virtual environment ----
    if [[ -d "$VENV_DIR" ]]; then
        warn "Virtual environment already exists at ${VENV_DIR}"
        read -rp "  Recreate it? [y/N] " answer
        if [[ "${answer,,}" == "y" ]]; then
            rm -rf "$VENV_DIR"
            info "Removed old venv"
        else
            info "Keeping existing venv"
        fi
    fi

    if [[ ! -d "$VENV_DIR" ]]; then
        python3 -m venv --system-site-packages "$VENV_DIR"
        info "Created virtual environment at ${VENV_DIR} (with system site-packages)"
    fi

    # ---- Upgrade pip ----
    "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
    info "Upgraded pip"

    # ---- Install requirements ----
    if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
        info "Installing requirements (requirements.txt)..."
        "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"
        info "Requirements installed"
    else
        warn "requirements.txt not found — skipping"
    fi

    echo ""
    echo "========================================================="
    echo "  Environment setup complete!"
    echo "========================================================="
    echo ""
    echo "  venv location:  ${VENV_DIR}"
    echo "  Python:         ${VENV_DIR}/bin/python3"
    echo "  pip:            ${VENV_DIR}/bin/pip"
    echo ""
    echo "  To activate manually:"
    echo "    source ${VENV_DIR}/bin/activate"
    echo ""
}

# =====================================================================
# services — delegates to manager/setup/install.sh
# =====================================================================
do_services() {
    if [[ $EUID -ne 0 ]]; then
        error "The 'services' command must be run as root."
        echo "  Try:  sudo bash install.sh services"
        exit 1
    fi

    if [[ ! -f "${SETUP_DIR}/install.sh" ]]; then
        error "Service installer not found at ${SETUP_DIR}/install.sh"
        exit 1
    fi

    bash "${SETUP_DIR}/install.sh"
}

# =====================================================================
# uninstall — delegates to manager/setup/install.sh uninstall
# =====================================================================
do_uninstall() {
    if [[ $EUID -ne 0 ]]; then
        error "The 'uninstall' command must be run as root."
        echo "  Try:  sudo bash install.sh uninstall"
        exit 1
    fi

    if [[ ! -f "${SETUP_DIR}/install.sh" ]]; then
        error "Service installer not found at ${SETUP_DIR}/install.sh"
        exit 1
    fi

    bash "${SETUP_DIR}/install.sh" uninstall
}

# =====================================================================
# Main
# =====================================================================
COMMAND="${1:-}"

case "$COMMAND" in
    install)
        do_install
        ;;
    services)
        do_services
        ;;
    uninstall)
        do_uninstall
        ;;
    help|-h|--help)
        usage
        ;;
    "")
        # No argument: full setup (install + services)
        do_install
        echo "Setting up systemd services..."
        echo "(This requires root — you may be prompted for your password.)"
        echo ""
        sudo bash "${SCRIPT_DIR}/install.sh" services
        ;;
    *)
        error "Unknown command: ${COMMAND}"
        usage
        exit 1
        ;;
esac
echo ""
