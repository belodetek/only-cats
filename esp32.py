# pylint: disable=broad-exception-caught,too-many-instance-attributes
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
        self.last_ack_at: float = 0.0

    @property
    def lock_until(self) -> float:
        """Return the Unix timestamp when the current lockout expires."""
        return self.state.until

    @property
    def is_connected(self) -> bool:
        """Return True when the underlying serial handle is open."""
        return bool(self.ser and getattr(self.ser, "is_open", False))

    @property
    def on_lockout_expired(self) -> Optional[Callable[[], None]]:
        """Return the callback executed when a prey lockout expires."""
        return self.state.on_expired

    @on_lockout_expired.setter
    def on_lockout_expired(self, callback: Optional[Callable[[], None]]) -> None:
        self.state.on_expired = callback

    def connect(self) -> bool:
        """Establish the serial connection to the ESP32 device."""
        try:
            with self.lock:
                if self.ser is not None:
                    try:
                        self.ser.close()
                    except (serial.SerialException, OSError):
                        pass
                    self.ser = None

            new_ser = serial.Serial(
                self.port,
                self.baudrate,
                timeout=0.1,
                write_timeout=0.5,
            )
            time.sleep(2.0)  # Allow ESP32 auto-reset to settle
            with self.lock:
                self.ser = new_ser
                self.last_ack_at = time.time()
            logger.info("Connected to ESP32 on %s at %d baud", self.port, self.baudrate)
            return True
        except (serial.SerialException, OSError) as exc:
            logger.error("Failed to open serial port %s: %s", self.port, exc)
            with self.lock:
                self.ser = None
            return False

    def _disconnect_locked(self) -> None:
        """Close and clear broken serial handle while holding self.lock."""
        if self.ser is not None:
            try:
                self.ser.close()
            except (serial.SerialException, OSError):
                pass
            self.ser = None

    def _drain_acks_locked(self) -> Optional[str]:
        """Read any pending response lines from firmware while holding self.lock."""
        if not self.ser or not getattr(self.ser, "is_open", False):
            return None
        last_line: Optional[str] = None
        in_waiting = getattr(self.ser, "in_waiting", 0)
        while isinstance(in_waiting, int) and in_waiting > 0:
            raw = self.ser.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="ignore").strip()
            if line:
                last_line = line
                if line.startswith("ACK:"):
                    self.last_ack_at = time.time()
                    logger.debug("ESP32 response: %s", line)
                elif line.startswith("EVENT:"):
                    logger.info("ESP32 event: %s", line)
            in_waiting = getattr(self.ser, "in_waiting", 0)
        return last_line

    def _write_locked(self, payload: bytes) -> bool:
        """Write command bytes and read any pending ACKs while holding self.lock."""
        if not self.ser or not getattr(self.ser, "is_open", False):
            return False
        try:
            self.ser.write(payload)
            if hasattr(self.ser, "flush"):
                self.ser.flush()
            self._drain_acks_locked()
            return True
        except (serial.SerialException, OSError) as exc:
            logger.error("Serial write failed (will reconnect): %s", exc)
            self._disconnect_locked()
            return False

    def ping(self) -> bool:
        """Send 'P' health ping to verify the ESP32 firmware loop is responsive."""
        with self.lock:
            return self._write_locked(b"P")

    def start_worker(self) -> None:
        """Spawn the background thread that manages reconnection and lock keepalives."""
        if self.thread and self.thread.is_alive():
            return
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._command_loop, daemon=True)
        self.thread.start()
        logger.info("Serial command thread started.")

    def _command_loop(self) -> None:
        """Reconnects if disconnected, sends 'L' while locked, and fires expiration once."""
        reconnect_delay = config.serial_reconnect_base_delay_sec

        while not self._stop_event.is_set():
            with self.lock:
                connected = bool(self.ser and getattr(self.ser, "is_open", False))

            if not connected:
                if self.connect():
                    reconnect_delay = config.serial_reconnect_base_delay_sec
                    with self.lock:
                        if time.time() < self.state.until:
                            self._write_locked(b"L")
                else:
                    self._stop_event.wait(reconnect_delay)
                    reconnect_delay = min(
                        reconnect_delay * 2.0, config.serial_reconnect_max_delay_sec
                    )
                    continue

            now = time.time()
            should_dispense = False
            with self.lock:
                if now < self.state.until:
                    if self._write_locked(b"L"):
                        logger.debug("Lock keepalive sent: 'L'")
                elif self.state.pending_dispense:
                    self.state.pending_dispense = False
                    should_dispense = True
                else:
                    try:
                        self._drain_acks_locked()
                    except (serial.SerialException, OSError) as exc:
                        logger.error("Serial read failed (will reconnect): %s", exc)
                        self._disconnect_locked()

            if should_dispense and self.state.on_expired:
                try:
                    logger.info("Prey lockout expired; triggering dispenser callback.")
                    self.state.on_expired()
                except Exception as exc:
                    logger.error("Error in on_lockout_expired callback: %s", exc)

            self._stop_event.wait(config.command_interval_sec)

    def trigger_lock(
        self,
        duration: Optional[float] = None,
        dispense_on_expire: bool = True,
    ) -> None:
        """Engage the lock and send 'L' for the specified duration."""
        effective_duration = (
            config.lockout_duration_sec if duration is None else duration
        )
        with self.lock:
            new_target = time.time() + effective_duration
            self.state.until = max(self.state.until, new_target)
            if dispense_on_expire:
                self.state.pending_dispense = True
            self._write_locked(b"L")
            logger.warning(
                ">>> PREY LOCKOUT ACTIVATED: Holding lock ON for %.1fs (until %s)",
                effective_duration,
                time.strftime("%H:%M:%S", time.localtime(self.state.until)),
            )

    def close(self) -> None:
        """Stop background worker and terminate serial connection."""
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        with self.lock:
            if self.ser and getattr(self.ser, "is_open", False):
                try:
                    self.ser.close()
                except (serial.SerialException, OSError):
                    pass
            self.ser = None
        logger.info("ESP32 serial connection closed.")
