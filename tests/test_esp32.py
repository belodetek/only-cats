"""Unit tests for esp32.py serial lock controller."""

import time
from unittest.mock import MagicMock, patch

import esp32


def test_trigger_lock_sends_keepalive_and_fires_expiration_once(monkeypatch):
    """Verify 'L' is sent during lockout and on_lockout_expired fires once upon unlock."""
    monkeypatch.setattr(esp32.config, "command_interval_sec", 0.01)

    mock_serial_instance = MagicMock()
    mock_serial_instance.is_open = True
    expired_events = []

    with patch("esp32.serial.Serial", return_value=mock_serial_instance):
        ctrl = esp32.ESP32SerialController(
            esp32.config.serial_port, esp32.config.baud_rate
        )
        ctrl.on_lockout_expired = lambda: expired_events.append(time.time())
        with patch("esp32.time.sleep"):
            ctrl.connect()
        ctrl.start_worker()

        ctrl.trigger_lock(duration=0.08, dispense_on_expire=True)
        time.sleep(0.18)
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
