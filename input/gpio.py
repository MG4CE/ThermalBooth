"""
GPIO button handler for Raspberry Pi.
Monitors a single physical button and triggers a callback on press.
"""

import json
import logging

try:
    from gpiozero import Button  # type: ignore
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    print("Warning: gpiozero not available. Running in simulation mode.")

logger = logging.getLogger(__name__)


class GPIOHandler:
    """Handle a single GPIO shutter button."""

    def __init__(self, config_path='config.json', callback=None):
        """
        Initialize GPIO handler.

        Args:
            config_path: Path to configuration file.
            callback: Zero-argument callable invoked when the button is pressed.
        """
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.pin = self.config['gpio']['pin']
        self.bounce_time = self.config['gpio']['bounce_time'] / 1000.0
        self.callback = callback
        self.button = None

        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available — simulation mode")
            return

        self._setup_gpio()

    def _setup_gpio(self):
        """Configure the GPIO button using gpiozero."""
        if not GPIO_AVAILABLE:
            return

        try:
            pull_up = self.config['gpio'].get('pull_up_down', 'pull_up') == 'pull_up'
            self.button = Button(
                self.pin,
                pull_up=pull_up,
                bounce_time=self.bounce_time,
            )
            self.button.when_pressed = lambda: self._on_press()
            logger.info(f"GPIO pin {self.pin} configured successfully")
        except Exception as e:
            logger.error(f"GPIO setup failed on pin {self.pin}: {e}")

    def _on_press(self):
        """Internal callback fired by gpiozero."""
        logger.info("Shutter button pressed")
        if self.callback:
            try:
                self.callback()
            except Exception as e:
                logger.error(f"Error in button callback: {e}")

    def simulate_press(self):
        """Simulate a button press (for testing without hardware)."""
        logger.info("Simulating button press")
        self._on_press()

    def cleanup(self):
        """Release GPIO resources."""
        if GPIO_AVAILABLE and self.button:
            try:
                self.button.close()
                self.button = None
                logger.info("GPIO cleanup complete")
            except Exception as e:
                logger.error(f"Error during GPIO cleanup: {e}")

    def __del__(self):
        self.cleanup()
