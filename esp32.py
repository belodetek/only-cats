"""USB serial controller for the ESP32 door lock and lockout timer."""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

# pylint: disable=import-error
import serial

import config

# pylint: enable=import-error

logger = logging.getLogger(config.app_name)


@dataclass
class LockoutState:
    """Tracks active lockout timer and expiration callback state."""

    until: float = 0.0
    pending_dispense: bool = False
    on_expired: Optional[Callable[[], None]] = None


class ESP32SerialController:
    """Manages the USB serial link to the ESP32 and runs the lock command loop."""

    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state = LockoutState()

    @property
    def lock_until(self) -> float:
        """Return the Unix timestamp when the current lockout expires."""
        return self.state.until

    @property
    def on_lockout_expired(self) -> Optional[Callable[[], None]]:
        """Return the callback executed when a prey lockout expires."""
        return self.state.on_expired

    @on_lockout_expired.setter
    def on_lockout_expired(self, callback: Optional[Callable[[], None]]) -> None:
        self.state.on_expired = callback

    def connect(self) -> None:
        """Establish the serial connection to the ESP32 device."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
            time.sleep(2.0)  # Allow ESP32 auto-reset to settle
            logger.info("Connected to ESP32 on %s at %d baud", self.port, self.baudrate)
        except (serial.SerialException, OSError) as exc:
            logger.error("Failed to open serial port %s: %s", self.port, exc)
            self.ser = None

    def start_worker(self) -> None:
        """Spawn the background thread that feeds the active lock command."""
        if self.ser and self.ser.is_open:
            self._stop_event.clear()
            self.thread = threading.Thread(target=self._command_loop, daemon=True)
            self.thread.start()
            logger.info("Serial command thread started.")

    def _command_loop(self) -> None:
        """Sends 'L' each second while locked; fires expiration callback once unlocked."""
        while not self._stop_event.is_set():
            now = time.time()
            should_dispense = False
            with self.lock:
                if now < self.state.until:
                    if self.ser and self.ser.is_open:
                        try:
                            self.ser.write(b"L")
                            logger.debug("Lock keepalive sent: 'L'")
                        except serial.SerialException as exc:
                            logger.error("Serial write failed: %s", exc)
                elif self.state.pending_dispense:
                    self.state.pending_dispense = False
                    should_dispense = True

            if should_dispense and self.state.on_expired:
                logger.info("Prey lockout expired; triggering dispenser callback.")
                self.state.on_expired()

            self._stop_event.wait(config.command_interval_sec)

    def trigger_lock(
        self,
        duration: float = config.lockout_duration_sec,
        dispense_on_expire: bool = True,
    ) -> None:
        """Engage the lock and send 'L' for the specified duration."""
        with self.lock:
            new_target = time.time() + duration
            self.state.until = max(self.state.until, new_target)
            if dispense_on_expire:
                self.state.pending_dispense = True
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(b"L")
                except serial.SerialException:
                    pass
            logger.warning(
                ">>> PREY LOCKOUT ACTIVATED: Holding lock ON for %.1fs (until %s)",
                duration,
                time.strftime("%H:%M:%S", time.localtime(self.state.until)),
            )

    def close(self) -> None:
        """Stop background worker and terminate serial connection."""
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except (serial.SerialException, OSError):
                    pass
        logger.info("ESP32 serial connection closed.")
