"""
Unified printer management interface.
USB ESC/POS only — Bluetooth and StarTSP support removed for simplicity.
"""

import json
import logging
import time
from typing import Optional

from .escpos_printer import ESCPOSPrinter
from .exceptions import PrinterError, InvalidConfigurationError

logger = logging.getLogger(__name__)


class PrinterManager:
    """
    Unified printer management interface (USB ESC/POS).
    """

    def __init__(self, config_path: str = 'config.json'):
        """
        Initialize printer manager with configuration.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self.config = self._load_config(config_path)

        self.printer: Optional[ESCPOSPrinter] = None
        self.simulation_mode = False
        self.is_connected = False
        self.connection_type = None

        logger.info("[Manager] " + "=" * 60)
        logger.info("[Manager] PrinterManager Initialization (USB ESC/POS)")
        logger.info("[Manager] " + "=" * 60)

        # Attempt to connect to printer
        result = self.connect()
        if not result:
            self.simulation_mode = True
            logger.warning("[Manager] RUNNING IN SIMULATION MODE (NO PRINTER)")
        else:
            logger.info(f"[Manager] PRINTER CONNECTED via {self.connection_type}")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self, config_path: str) -> dict:
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            raise InvalidConfigurationError(
                f"Failed to load config from {config_path}",
                context={'path': config_path, 'error': str(e)}
            )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to the USB ESC/POS printer."""
        try:
            printer_cfg = self.config['printer']
            if not self.printer:
                retry = printer_cfg.get('retry_attempts', 3)
                line_spacing = printer_cfg.get('line_spacing', 30)
                heat_time = printer_cfg.get('heat_time', 30)
                max_dots = printer_cfg.get('max_dots', 5)
                self.printer = ESCPOSPrinter(
                    retry_attempts=retry,
                    line_spacing=line_spacing,
                    heat_time=heat_time,
                    max_dots=max_dots,
                )

            success = self.printer.connect_usb(
                vendor_id=printer_cfg.get('vendor_id'),
                product_id=printer_cfg.get('product_id'),
                auto_detect=printer_cfg.get('auto_detect', True),
            )

            if success:
                self.is_connected = True
                self.simulation_mode = False
                self.connection_type = 'usb'
            else:
                self.is_connected = False
                self.connection_type = None

            return success
        except Exception as e:
            logger.error(f"[Manager] Connection error: {e}")
            self.is_connected = False
            self.connection_type = None
            return False

    def disconnect(self):
        """Disconnect from printer."""
        if self.printer:
            self.printer.disconnect()
            self.printer = None
        self.is_connected = False
        self.connection_type = None
        logger.info("[Manager] Printer disconnected")

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------

    def print_image(self, image_path: str) -> bool:
        """
        Print an image.

        Args:
            image_path: Path to the processed image file.

        Returns:
            True on success.
        """
        if self.simulation_mode:
            logger.info(f"[Manager] Simulation: would print {image_path}")
            return True

        if not self.printer:
            logger.error("[Manager] No printer instance")
            return False

        try:
            success = self.printer.print_image(image_path, auto_reconnect=True)
            if success:
                self.is_connected = self.printer.is_connected()
            return success
        except Exception as e:
            logger.error(f"[Manager] Print failed: {e}")
            self.is_connected = False
            return False

    def test_print(self) -> bool:
        """Print a test page."""
        if self.simulation_mode:
            logger.info("[Manager] Simulation: would print test pattern")
            return True

        if not self.is_connected:
            if not self.connect():
                return False

        if not self.printer:
            return False

        try:
            success = self.printer.test_print()
            if success:
                self.is_connected = self.printer.is_connected()
            return success
        except Exception as e:
            logger.error(f"[Manager] Test print failed: {e}")
            self.is_connected = False
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        status = {
            'connected': self.is_connected,
            'protocol': 'escpos',
            'simulation_mode': self.simulation_mode,
            'connection_type': self.connection_type,
        }
        if self.printer and self.is_connected:
            try:
                status.update(self.printer.get_status())
            except Exception:
                pass
        return status

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
