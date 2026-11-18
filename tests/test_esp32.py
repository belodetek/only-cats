# pylint: disable=import-error
"""Unit tests for esp32.py serial lock controller."""

import threading
import time
from unittest.mock import MagicMock, patch

import esp32


def test_command_loop_reconnects_after_serial_disconnect(monkeypatch):
    """Verify _command_loop recovers from SerialException and re-asserts active lock."""
    monkeypatch.setattr(esp32.config, "command_interval_sec", 0.01)

    broken_serial = MagicMock()
    broken_serial.is_open = True
    broken_serial.in_waiting = 0
    broken_serial.write.side_effect = esp32.serial.SerialException("USB disconnected")

    recovered_serial = MagicMock()
    recovered_serial.is_open = True
    recovered_serial.in_waiting = 0
    recovered_event = threading.Event()

    def _on_recovered_write(_data):
        recovered_event.set()

    recovered_serial.write.side_effect = _on_recovered_write

    with patch(
        "esp32.serial.Serial", side_effect=[broken_serial, recovered_serial]
    ) as mock_serial_cls, patch("esp32.time.sleep"):
        ctrl = esp32.ESP32SerialController(
            esp32.config.serial_port, esp32.config.baud_rate
        )
        ctrl.connect()
        ctrl.start_worker()

        # First write hits broken_serial and triggers disconnect; worker reconnects and re-sends 'L'
        ctrl.trigger_lock(duration=0.5, dispense_on_expire=False)
        assert recovered_event.wait(
            timeout=1.5
        ), "Expected worker to reconnect and write 'L'"
        ctrl.close()

    assert mock_serial_cls.call_count == 2
    broken_serial.close.assert_called()
    recovered_serial.write.assert_called_with(b"L")


def test_trigger_lock_sends_keepalive_and_fires_expiration_once(monkeypatch):
    """Verify 'L' is sent during lockout and on_lockout_expired fires once upon unlock."""
    monkeypatch.setattr(esp32.config, "command_interval_sec", 0.01)

    two_writes_seen = threading.Event()
    expired_event = threading.Event()
    expired_events = []

    mock_serial_instance = MagicMock()
    mock_serial_instance.is_open = True

    def _on_write(_data):
        if mock_serial_instance.write.call_count >= 2:
            two_writes_seen.set()

    mock_serial_instance.write.side_effect = _on_write

    def _on_expired():
        expired_events.append(time.time())
        expired_event.set()

    with patch("esp32.serial.Serial", return_value=mock_serial_instance):
        ctrl = esp32.ESP32SerialController(
            esp32.config.serial_port, esp32.config.baud_rate
        )
        ctrl.on_lockout_expired = _on_expired
        with patch("esp32.time.sleep"):
            ctrl.connect()
        ctrl.start_worker()

        ctrl.trigger_lock(duration=0.15, dispense_on_expire=True)
        assert two_writes_seen.wait(timeout=1.0), "Expected at least 2 keepalive writes"
        assert expired_event.wait(timeout=1.0), "Expected lockout expiration callback"
        ctrl.close()

    assert mock_serial_instance.write.call_count >= 2
    mock_serial_instance.write.assert_called_with(b"L")
    assert len(expired_events) == 1
    mock_serial_instance.close.assert_called_once()


def test_trigger_lock_without_dispense_skips_expiration_callback(monkeypatch):
    """Verify dispense_on_expire=False unlocks silently without triggering dispenser."""
    monkeypatch.setattr(esp32.config, "command_interval_sec", 0.01)

    mock_serial_instance = MagicMock()
    mock_serial_instance.is_open = True
    expired_events = []

    with patch("esp32.serial.Serial", return_value=mock_serial_instance):
        ctrl = esp32.ESP32SerialController(
            esp32.config.serial_port, esp32.config.baud_rate
        )
        ctrl.on_lockout_expired = lambda: expired_events.append(True)
        with patch("esp32.time.sleep"):
            ctrl.connect()
        ctrl.start_worker()

        ctrl.trigger_lock(duration=0.05, dispense_on_expire=False)
        time.sleep(0.14)
        ctrl.close()

    assert not expired_events
