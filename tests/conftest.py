# pylint: disable=import-error
"""Shared pytest fixtures for iwatch-ulock unit tests."""

import ipaddress
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

import config


@pytest.fixture(autouse=True)
def _isolate_config_defaults(monkeypatch):
    """Ensure every test starts with predictable config values regardless of host/compose env."""
    monkeypatch.setattr(config, "app_name", "iwatch-ulock-test")
    monkeypatch.setattr(config, "camera_url", "https://192.168.10.108")
    monkeypatch.setattr(config, "camera_user", "test-user")
    monkeypatch.setattr(config, "camera_password", "test-password")
    monkeypatch.setattr(
        config,
        "camera_networks",
        {
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("192.168.10.0/24"),
        },
    )
    monkeypatch.setattr(config, "webhook_secret", "test-secret")
    monkeypatch.setattr(config, "in_training", False)
    monkeypatch.setattr(config, "conf_threshold", 0.55)
    monkeypatch.setattr(config, "target_classes", {"prey"})
    monkeypatch.setattr(config, "lockout_duration_sec", 5.0)
    monkeypatch.setattr(config, "command_interval_sec", 0.05)
    monkeypatch.setattr(config, "dispenser_url", "http://ifeed:8000/dispense")
    monkeypatch.setattr(config, "dispenser_user", "admin")
    monkeypatch.setattr(config, "dispenser_password", "secret")
    monkeypatch.setattr(config, "signal_api_url", "http://signal-api:8080")
    monkeypatch.setattr(config, "signal_sender", "+12505550100")
    monkeypatch.setattr(config, "signal_recipients", ["group.testGroupId123="])
    monkeypatch.setattr(config, "esp_chip", "esp32c6")
    monkeypatch.setattr(config, "esp_flash_baud", 460800)
    monkeypatch.setattr(config, "firmware_bin_path", "flash/firmware_sketch.ino.bin")
    monkeypatch.setattr(config, "serial_port", "/dev/null")
    monkeypatch.setattr(config, "baud_rate", 115200)


@pytest.fixture
def tmp_data_dirs(tmp_path, monkeypatch):
    """Redirect config.images_dir and config.labels_dir to isolated temp folders."""
    images_dir = tmp_path / "images"
    labels_dir = tmp_path / "labels"
    images_dir.mkdir()
    labels_dir.mkdir()
    monkeypatch.setattr(config, "images_dir", str(images_dir))
    monkeypatch.setattr(config, "labels_dir", str(labels_dir))
    return images_dir, labels_dir


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """Encode a synthetic 64x64 BGR frame as valid JPEG bytes."""
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[16:48, 16:48] = (0, 255, 0)
    # pylint: disable=no-member
    ok, buf = cv2.imencode(".jpg", frame)
    # pylint: enable=no-member
    assert ok
    return buf.tobytes()


def make_yolo_result(detections: list[tuple[int, float, list[float]]]):
    """Build a mock Ultralytics Results object with .boxes.cls, .conf, and .xywhn."""
    cls_arr = np.array([d[0] for d in detections], dtype=np.float32)
    conf_arr = np.array([d[1] for d in detections], dtype=np.float32)
    xywhn_arr = (
        np.array([d[2] for d in detections], dtype=np.float32)
        if detections
        else np.empty((0, 4), dtype=np.float32)
    )

    cls_tensor = MagicMock()
    cls_tensor.__iter__.return_value = iter(cls_arr)
    cls_tensor.cpu.return_value.numpy.return_value = cls_arr

    xywhn_tensor = MagicMock()
    xywhn_tensor.cpu.return_value.numpy.return_value = xywhn_arr

    boxes = MagicMock()
    boxes.__len__.return_value = len(detections)
    boxes.cls = cls_tensor
    boxes.conf = conf_arr
    boxes.xywhn = xywhn_tensor
    return SimpleNamespace(boxes=boxes)
