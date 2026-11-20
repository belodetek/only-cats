# pylint: disable=import-error,too-many-positional-arguments,too-many-arguments
"""Shared pytest fixtures for iwatch-ulock unit and browser tests."""

import ipaddress
import socket
import threading
import time
import urllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest
import uvicorn

import camera_receiver
import config


@pytest.fixture(autouse=True)
def _isolate_config_defaults(monkeypatch):
    """Ensure every test starts with predictable config values regardless of host/compose env."""
    monkeypatch.setattr(config, "app_name", "iwatch-ulock-test")
    monkeypatch.setattr(config, "app_version", "0.0.0")
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
    monkeypatch.setattr(config, "allowed_alarm_types", {"ANIMAL", "TEST"})
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
    monkeypatch.setattr(config, "serial_reconnect_base_delay_sec", 0.05)
    monkeypatch.setattr(config, "serial_reconnect_max_delay_sec", 0.2)
    monkeypatch.setattr(config, "dispenser_url", "https://dispenser.local.test/")


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


def bind_admin_override_mock(controller) -> None:
    """Wire mock controller admin_lock/admin_unlock side effects to update admin_override."""
    controller.admin_override = None

    def _set_locked() -> None:
        controller.admin_override = "locked"

    def _set_unlocked() -> None:
        controller.admin_override = "unlocked"

    controller.admin_lock.side_effect = _set_locked
    controller.admin_unlock.side_effect = _set_unlocked


def assert_admin_lock_unlock_flow(
    client,
    controller,
    lock_url: str,
    unlock_url: str,
    lock_kwargs: dict | None = None,
    unlock_kwargs: dict | None = None,
) -> None:
    """Assert POST lock/unlock endpoints update controller state and /health metrics."""
    lock_resp = client.post(lock_url, **(lock_kwargs or {}))
    assert lock_resp.status_code == 200
    assert lock_resp.json() == {"status": "locked", "admin_override": "locked"}
    controller.admin_lock.assert_called_once()

    health_locked = client.get("/health").json()
    assert health_locked["lock_engaged"] is True
    assert health_locked["admin_override"] == "locked"

    unlock_resp = client.post(unlock_url, **(unlock_kwargs or {}))
    assert unlock_resp.status_code == 200
    assert unlock_resp.json() == {"status": "unlocked", "admin_override": "unlocked"}
    controller.admin_unlock.assert_called_once()

    health_unlocked = client.get("/health").json()
    assert health_unlocked["lock_engaged"] is False
    assert health_unlocked["admin_override"] == "unlocked"


@pytest.fixture
def live_ui_server():
    """Run FastAPI app with mocked hardware state on an ephemeral localhost port."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    bind_admin_override_mock(controller)

    state = camera_receiver.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )
    camera_receiver.app.state.deps = state

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config_uv = uvicorn.Config(
        camera_receiver.app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config_uv)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5.0
    while not server.started and time.time() < deadline:
        time.sleep(0.02)

    yield base_url, state

    server.should_exit = True
    thread.join(timeout=3.0)


@pytest.fixture(scope="session")
def _session_traefik_uvicorn():
    """Start Uvicorn on 0.0.0.0:8000 and point Traefik directly to this container's IP."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    bind_admin_override_mock(controller)

    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )

    config_uv = uvicorn.Config(
        camera_receiver.app,
        host="0.0.0.0",
        port=8000,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config_uv)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_err: Exception | None = None
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/health", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last_err = exc
            time.sleep(0.05)
    else:
        raise RuntimeError(f"Uvicorn test server failed within 10s: {last_err!r}")

    # Flowzone 'docker compose run sut' doesn't create network aliases
    # .. so, resolve this container's bridge IP so Traefik reaches it
    # when '.. run' is used instead of '.. up'
    sut_ip = socket.gethostbyname(socket.gethostname())
    dynamic_dir = Path(__file__).resolve().parent.parent / "traefik" / "dynamic"
    override_file = dynamic_dir / "_test_upstream.yml"
    override_file.write_text(
        "http:\n"
        "  services:\n"
        "    iwatch-ulock-svc:\n"
        "      loadBalancer:\n"
        "        servers:\n"
        f"          - url: http://{sut_ip}:8000\n",
        encoding="utf-8",
    )

    # Wait until Traefik reloads _test_upstream.yml and routes /health -> 200
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            with opener.open(
                "http://test-device.balena-devices.com/health", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    break
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last_err = exc
            time.sleep(0.1)
    else:
        override_file.unlink(missing_ok=True)
        raise RuntimeError(
            f"Traefik did not reload {override_file} within 10s: {last_err!r}"
        )

    try:
        yield {
            "domain_https": "https://iwatch.local.test",
            "domain_http": "http://iwatch.local.test",
            "balena_http": "http://test-device.balena-devices.com",
        }
    finally:
        override_file.unlink(missing_ok=True)
        server.should_exit = True
        thread.join(timeout=3.0)


@pytest.fixture
def traefik_ui_server(_session_traefik_uvicorn):
    """Provide fresh mocked AppState per test backed by the shared port-8000 server."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    bind_admin_override_mock(controller)

    state = camera_receiver.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )
    camera_receiver.app.state.deps = state

    return {
        **_session_traefik_uvicorn,
        "state": state,
    }
