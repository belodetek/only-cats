# pylint: disable=import-error,too-many-positional-arguments,too-many-arguments
"""Shared pytest fixtures for iwatch-ulock unit and browser tests."""

import ipaddress
import os
import socket
import threading
import time
import urllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cv2
import httpx
import numpy as np
import pytest
import uvicorn
from playwright.sync_api import Page, expect

import api_routes
import config
import esp32
import evaluator
import metrics
import only_cats
import web_ui

TRAEFIK_UPSTREAM_FILE = (
    Path(__file__).resolve().parent.parent
    / "traefik"
    / "dynamic"
    / "_test_upstream.yml"
)

HIL_APP_URL = os.getenv("HIL_APP_URL", "http://sut-hil:8000")
_EMU_HOST = os.getenv("HIL_EMU_HOST", "esp32c6-emulator")
_EMU_PORT = os.getenv("CONTROL_API_PORT", "9001")
HIL_EMU_URL = os.getenv("HIL_EMU_URL", f"http://{_EMU_HOST}:{_EMU_PORT}")

_BASE_CONFIG_OVERRIDES: dict[str, object] = {
    "app_name": "iwatch-ulock-test",
    "app_version": "0.0.0",
    "repo_url": "https://github.com/belodetek/only-cats",
    "camera_url": "https://192.168.10.108",
    "camera_user": "test-user",
    "camera_password": "test-password",
    "camera_networks": {
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("192.168.0.0/16"),
    },
    "webhook_secret": "test-secret",
    "allowed_alarm_types": {"ANIMAL", "TEST"},
    "in_training": False,
    "min_blur_variance": 65.0,
    "conf_threshold": 0.55,
    "target_classes": {"prey"},
    "lockout_duration_sec": 5.0,
    "enable_animal_prelock": True,
    "animal_prelock_duration_sec": 1.0,
    "animal_prelock_cooldown_sec": 4.0,
    "command_interval_sec": 0.05,
    "dispenser_url": "https://dispenser.local.test/",
    "dispenser_user": "admin",
    "dispenser_password": "secret",
    "signal_api_url": "http://signal-api:8080",
    "signal_sender": "+12505550100",
    "signal_recipients": ["group.testGroupId123="],
    "esp_chip": "esp32c6",
    "esp_flash_baud": 460800,
    "firmware_bin_path": "flash/firmware_sketch.ino.bin",
    "serial_port": "/dev/null",
    "baud_rate": 115200,
    "serial_reconnect_base_delay_sec": 0.05,
    "serial_reconnect_max_delay_sec": 0.2,
}

_HIL_CONFIG_OVERRIDES: dict[str, object] = {
    "camera_url": os.getenv("HIL_CAM_URL", "http://mock-camera:8080"),
    "camera_user": config.camera_user,
    "camera_password": config.camera_password,
    "webhook_secret": config.webhook_secret,
    "in_training": config.in_training,
    "min_blur_variance": config.min_blur_variance,
    "dispenser_url": "",
    "signal_sender": "",
    "signal_recipients": [],
    "firmware_bin_path": config.firmware_bin_path,
    "serial_port": config.serial_port,
    "serial_reconnect_base_delay_sec": config.serial_reconnect_base_delay_sec,
    "serial_reconnect_max_delay_sec": config.serial_reconnect_max_delay_sec,
    "enable_animal_prelock": config.enable_animal_prelock,
}


def _apply_config_overrides(is_hil: bool, setter) -> None:
    """Apply unit or HiL config defaults through the provided attribute setter."""
    merged = (
        {**_BASE_CONFIG_OVERRIDES, **_HIL_CONFIG_OVERRIDES}
        if is_hil
        else _BASE_CONFIG_OVERRIDES
    )
    for key, value in merged.items():
        setter(config, key, value)


@pytest.fixture(scope="session", autouse=True)
def _init_hil_session_config(request):
    """Populate HiL config defaults before session-scoped HiL fixtures run."""
    if any(item.get_closest_marker("hil") for item in request.session.items):
        _apply_config_overrides(is_hil=True, setter=setattr)


@pytest.fixture(autouse=True)
def _isolate_config_defaults(request, monkeypatch):
    """Ensure every test starts with predictable config values regardless of host/compose env."""
    is_hil = request.node.get_closest_marker("hil") is not None
    _apply_config_overrides(is_hil=is_hil, setter=monkeypatch.setattr)


def stub_external_cdns(page, base_url: str) -> None:
    """Fulfill external CDN scripts immediately so browser checks work offline."""
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(base_url)
            else route.fulfill(
                status=200, content_type="application/javascript", body=""
            )
        ),
    )


def open_first_dataset_triage_modal(page: Page) -> None:
    """Open the dataset drawer, click the first card, and wait for the triage modal."""
    page.locator("#btn-dataset").click()
    expect(page.locator("#dataset-panel")).to_be_visible()
    page.locator("#dataset-grid [data-ds-idx='0']").click()
    expect(page.locator("#triage-modal")).to_be_visible()


def write_traefik_upstream(url: str) -> Path:
    """Write the dynamic Traefik upstream YAML pointing iwatch-ulock-svc at url."""
    TRAEFIK_UPSTREAM_FILE.write_text(
        "http:\n"
        "  services:\n"
        "    iwatch-ulock-svc:\n"
        "      loadBalancer:\n"
        "        servers:\n"
        f"          - url: {url}\n",
        encoding="utf-8",
    )
    return TRAEFIK_UPSTREAM_FILE


def trigger_camera_webhook(alarm_type: str) -> dict:
    """Ask mock-camera to POST a Reolink webhook from its own container IP."""
    resp = httpx.post(
        f"{config.camera_url}/trigger-webhook",
        json={
            "target_url": f"{HIL_APP_URL}/webhook/reolink?secret={config.webhook_secret}",
            "secret": config.webhook_secret,
            "payload": {"alarm": {"type": alarm_type}},
        },
        timeout=5.0,
    )
    resp.raise_for_status()
    return resp.json()


def _patch_metrics_store(monkeypatch, store: metrics.MetricsStore) -> None:
    """Bind an isolated MetricsStore across metrics and all importing modules."""
    for mod in (metrics, esp32, api_routes, web_ui, evaluator):
        monkeypatch.setattr(mod, "METRICS", store)


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
    """Wire mock controller admin_lock/admin_unlock/admin_auto side effects
    to update admin_override."""
    controller.admin_override = None

    def _set_locked() -> None:
        controller.admin_override = "locked"

    def _set_unlocked() -> None:
        controller.admin_override = "unlocked"

    def _set_auto() -> None:
        controller.admin_override = None

    controller.admin_lock.side_effect = _set_locked
    controller.admin_unlock.side_effect = _set_unlocked
    controller.admin_auto.side_effect = _set_auto


def _with_ui_csrf_header(url: str, kwargs: dict | None) -> dict:
    """Attach X-Requested-With header automatically for browser /ui/* POST routes."""
    merged = dict(kwargs or {})
    if url.startswith("/ui/"):
        merged["headers"] = {
            "X-Requested-With": "fetch",
            **merged.get("headers", {}),
        }
    return merged


def assert_admin_lock_unlock_flow(
    client,
    controller,
    lock_url: str,
    unlock_url: str,
    lock_kwargs: dict | None = None,
    unlock_kwargs: dict | None = None,
    auto_url: str | None = None,
    auto_kwargs: dict | None = None,
) -> None:
    """Assert POST lock/unlock/auto endpoints update controller state and /health metrics."""
    lock_resp = client.post(lock_url, **_with_ui_csrf_header(lock_url, lock_kwargs))
    assert lock_resp.status_code == 200
    assert lock_resp.json() == {"status": "locked", "admin_override": "locked"}
    controller.admin_lock.assert_called_once()

    health_locked = client.get("/health").json()
    assert health_locked["lock_engaged"] is True
    assert health_locked["admin_override"] == "locked"

    unlock_resp = client.post(
        unlock_url, **_with_ui_csrf_header(unlock_url, unlock_kwargs)
    )
    assert unlock_resp.status_code == 200
    assert unlock_resp.json() == {"status": "unlocked", "admin_override": "unlocked"}
    controller.admin_unlock.assert_called_once()

    health_unlocked = client.get("/health").json()
    assert health_unlocked["lock_engaged"] is False
    assert health_unlocked["admin_override"] == "unlocked"

    if auto_url is not None:
        auto_resp = client.post(auto_url, **_with_ui_csrf_header(auto_url, auto_kwargs))
        assert auto_resp.status_code == 200
        assert auto_resp.json() == {"status": "auto", "admin_override": None}
        controller.admin_auto.assert_called_once()

        health_auto = client.get("/health").json()
        assert health_auto["lock_engaged"] is False
        assert health_auto["admin_override"] is None


@pytest.fixture
def live_ui_server():
    """Run FastAPI app with mocked hardware state on an ephemeral localhost port."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    bind_admin_override_mock(controller)

    state = only_cats.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )
    only_cats.app.state.deps = state

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config_uv = uvicorn.Config(
        only_cats.app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
        timeout_graceful_shutdown=0.5,
    )
    server = uvicorn.Server(config_uv)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with opener.open(f"{base_url}/health", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:  # pylint: disable=broad-exception-caught
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

    only_cats.app.state.deps = only_cats.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )

    config_uv = uvicorn.Config(
        only_cats.app,
        host="0.0.0.0",
        port=8000,
        log_level="error",
        lifespan="off",
        timeout_graceful_shutdown=0.5,
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
    override_file = write_traefik_upstream(f"http://{sut_ip}:8000")

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

    state = only_cats.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )
    only_cats.app.state.deps = state

    return {
        **_session_traefik_uvicorn,
        "state": state,
    }
