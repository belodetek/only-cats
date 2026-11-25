"""Unit tests for FastAPI routes in routes.py (/webhook/reolink, /lock, /unlock, /health)."""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

# pylint: disable=import-error
from fastapi.testclient import TestClient

# pylint: enable=import-error
import api_routes
import config
import esp32
import evaluator
import only_cats
from flasher import ESP_APP_DESC_MAGIC, AppDescriptor
from state import AppState
from tests.conftest import (
    assert_admin_lock_unlock_flow,
    bind_admin_override_mock,
    make_yolo_result,
)


def _make_state() -> AppState:
    """Build an AppState with mocked controller, model, and HTTP client."""
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0
    return AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )


def test_webhook_logging_redacts_secrets_and_auth_headers(caplog):
    """Verify webhook request logs mask ?secret= query params and credential headers."""
    only_cats.app.state.deps = _make_state()
    secret = config.webhook_secret

    with (
        caplog.at_level(logging.INFO, logger=api_routes.logger.name),
        patch("api_routes.fetch_and_evaluate", new_callable=AsyncMock),
    ):
        client = TestClient(only_cats.app, client=("192.168.10.108", 50000))
        resp = client.post(
            "/webhook/reolink",
            params={"secret": secret, "channel": "0"},
            headers={
                "X-Webhook-Secret": secret,
                "Authorization": "Bearer super-secret-bearer",
            },
            json={"alarm": {"type": "TEST"}},
        )

    assert resp.status_code == 200
    app_logs = "\n".join(
        r.getMessage() for r in caplog.records if r.name == api_routes.logger.name
    )
    assert app_logs
    assert secret not in app_logs
    assert "super-secret-bearer" not in app_logs
    assert "%5BREDACTED%5D" in app_logs or "[REDACTED]" in app_logs
    assert "channel=0" in app_logs


def test_webhook_and_health_endpoints():
    """Verify FastAPI /webhook/reolink and /health routes with mocked AppState."""
    state = _make_state()
    only_cats.app.state.deps = state
    secret = config.webhook_secret

    with patch("api_routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            only_cats.app,
            client=("192.168.10.108", 50000),
            raise_server_exceptions=True,
        )

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["serial_connected"] is True

        hook_resp = client.post(
            "/webhook/reolink",
            params={"secret": secret},
            json={"alarm": {"type": "TEST"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        assert hook_resp.json()["camera_url"] == "https://192.168.10.108"

        state.controller.trigger_lock.assert_not_called()
        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == "https://192.168.10.108"
        assert args[2]["camera_url"] == "https://192.168.10.108"
        assert args[2]["alarm_type"] == "TEST"


def test_webhook_accepts_x_webhook_secret_header():
    """Verify webhook endpoint accepts shared secret via X-Webhook-Secret header."""
    only_cats.app.state.deps = _make_state()

    with patch("api_routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            only_cats.app,
            client=("192.168.10.108", 50000),
            raise_server_exceptions=True,
        )

        hook_resp = client.post(
            "/webhook/reolink",
            headers={"X-Webhook-Secret": config.webhook_secret},
            json={"alarm": {"type": "TEST"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        mock_eval.assert_awaited_once()


def test_webhook_rejects_missing_or_invalid_secret():
    """Verify webhook endpoint returns 401 when secret is missing or invalid."""
    only_cats.app.state.deps = _make_state()
    client = TestClient(
        only_cats.app,
        client=("192.168.10.108", 50000),
        raise_server_exceptions=False,
    )

    resp_missing = client.post("/webhook/reolink", json={"alarm": {"type": "TEST"}})
    assert resp_missing.status_code == 401
    assert resp_missing.json()["detail"] == "Invalid webhook secret"

    resp_bad = client.post(
        "/webhook/reolink",
        params={"secret": "wrong-secret"},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp_bad.status_code == 401
    assert resp_bad.json()["detail"] == "Invalid webhook secret"

    resp_bad_hdr = client.post(
        "/webhook/reolink",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp_bad_hdr.status_code == 401
    assert resp_bad_hdr.json()["detail"] == "Invalid webhook secret"


def test_webhook_rejects_untrusted_client_ip():
    """Verify webhook endpoint returns 403 when client IP is not in camera_networks."""
    only_cats.app.state.deps = _make_state()
    client = TestClient(
        only_cats.app,
        client=("2001:db8::1", 50000),
        raise_server_exceptions=False,
    )
    resp = client.post(
        "/webhook/reolink",
        params={"secret": config.webhook_secret},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Client IP not in trusted camera subnet"


def test_webhook_resolves_default_camera_url_when_client_host_unknown():
    """Verify webhook endpoint falls back to config.camera_url when client host is unknown."""
    state = _make_state()
    only_cats.app.state.deps = state
    expected_url = config.camera_url

    with patch("api_routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            only_cats.app,
            client=("unknown", 0),
            raise_server_exceptions=True,
        )

        hook_resp = client.post(
            "/webhook/reolink",
            params={"secret": config.webhook_secret},
            json={"alarm": {"type": "ANIMAL"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        assert hook_resp.json()["camera_url"] == expected_url

        state.controller.trigger_lock.assert_called_once_with(
            config.animal_prelock_duration_sec, dispense_on_expire=False
        )
        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == expected_url
        assert args[2]["camera_url"] == expected_url


def test_webhook_ignores_non_whitelisted_alarm_types():
    """Verify webhook ignores alarm types not in config.allowed_alarm_types."""
    state = _make_state()
    only_cats.app.state.deps = state
    secret = config.webhook_secret

    with patch("api_routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            only_cats.app,
            client=("192.168.10.108", 50000),
            raise_server_exceptions=True,
        )

        ignored_resp = client.post(
            "/webhook/reolink",
            params={"secret": secret},
            json={"alarm": {"type": "PEOPLE"}},
        )
        assert ignored_resp.status_code == 200
        assert ignored_resp.json()["status"] == "ignored"
        assert ignored_resp.json()["alarm_type"] == "PEOPLE"
        state.controller.trigger_lock.assert_not_called()
        mock_eval.assert_not_awaited()

        animal_resp = client.post(
            "/webhook/reolink",
            params={"secret": secret},
            json={"alarm": {"type": "ANIMAL"}},
        )
        assert animal_resp.status_code == 200
        assert animal_resp.json()["status"] == "queued"
        state.controller.trigger_lock.assert_called_once_with(
            config.animal_prelock_duration_sec, dispense_on_expire=False
        )
        mock_eval.assert_awaited_once()


def test_animal_webhook_prelocks_immediately_and_extends_on_prey_match(monkeypatch):
    """ANIMAL webhook locks for prelock duration immediately, then extends on prey match."""
    monkeypatch.setattr(config, "animal_prelock_duration_sec", 15.0)
    monkeypatch.setattr(config, "lockout_duration_sec", 300.0)

    controller = esp32.ESP32SerialController("/dev/null", 115200)
    mock_http = AsyncMock()
    mock_http.get.return_value = MagicMock(status_code=200, content=b"fake-jpeg")
    only_cats.app.state.deps = AppState(
        controller=controller,
        model=MagicMock(names={0: "prey"}),
        http_client=mock_http,
    )

    monkeypatch.setattr(
        evaluator,
        "run_inference",
        lambda *_args: (
            MagicMock(),
            [make_yolo_result([(0, 0.92, [0.5, 0.5, 0.2, 0.2])])],
        ),
    )
    monkeypatch.setattr(evaluator, "persist_and_notify", AsyncMock())

    calls: list[tuple[float | None, bool]] = []
    orig_trigger = controller.trigger_lock

    def _spy_trigger(duration=None, dispense_on_expire=True):
        calls.append((duration, dispense_on_expire))
        return orig_trigger(duration=duration, dispense_on_expire=dispense_on_expire)

    monkeypatch.setattr(controller, "trigger_lock", _spy_trigger)

    t_before = time.time()
    client = TestClient(only_cats.app, client=("192.168.10.108", 50000))
    resp = client.post(
        "/webhook/reolink",
        params={"secret": config.webhook_secret},
        json={"alarm": {"type": "ANIMAL"}},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert calls == [
        (15.0, False),
        (300.0, True),
    ]
    assert controller.lock_until >= t_before + 299.0
    assert controller.state.pending_dispense is True


def test_animal_webhook_prelock_expires_without_dispense_when_no_prey(monkeypatch):
    """ANIMAL webhook holds pre-lock without extending or dispensing when no prey matches."""
    monkeypatch.setattr(config, "animal_prelock_duration_sec", 15.0)
    monkeypatch.setattr(config, "lockout_duration_sec", 300.0)

    controller = esp32.ESP32SerialController("/dev/null", 115200)
    mock_http = AsyncMock()
    mock_http.get.return_value = MagicMock(status_code=200, content=b"fake-jpeg")
    only_cats.app.state.deps = AppState(
        controller=controller,
        model=MagicMock(names={0: "prey"}),
        http_client=mock_http,
    )

    monkeypatch.setattr(
        evaluator,
        "run_inference",
        lambda *_args: (MagicMock(), [make_yolo_result([])]),
    )

    t_before = time.time()
    client = TestClient(only_cats.app, client=("192.168.10.108", 50000))
    resp = client.post(
        "/webhook/reolink",
        params={"secret": config.webhook_secret},
        json={"alarm": {"type": "ANIMAL"}},
    )

    assert resp.status_code == 200
    assert t_before + 14.0 <= controller.lock_until <= t_before + 17.0
    assert controller.state.pending_dispense is False


def test_admin_lock_and_unlock_endpoints():
    """Verify /lock and /unlock enforce auth, update controller state, and reflect in /health."""
    state = _make_state()
    bind_admin_override_mock(state.controller)
    only_cats.app.state.deps = state

    secret = config.webhook_secret
    client = TestClient(only_cats.app, raise_server_exceptions=False)

    assert client.post("/lock").status_code == 401
    assert client.post("/unlock").status_code == 401

    assert_admin_lock_unlock_flow(
        client=client,
        controller=state.controller,
        lock_url="/lock",
        unlock_url="/unlock",
        lock_kwargs={"headers": {"X-Webhook-Secret": secret}},
        unlock_kwargs={"params": {"secret": secret}},
    )


def test_health_includes_esp32_firmware_metadata():
    """Verify /health serializes chip and local firmware descriptor fields."""
    desc = AppDescriptor(
        magic=ESP_APP_DESC_MAGIC,
        version="a1b2c3d",
        project_name="only-cats-lock",
        time="12:00:00",
        date="Nov 20 2026",
        idf_ver="v5.1.4",
        app_elf_sha256=b"\xde\xad\xbe\xef" + b"\x00" * 28,
    )
    state = _make_state()
    state.esp32_chip_desc = desc
    state.esp32_local_desc = desc
    only_cats.app.state.deps = state
    only_cats.app.state.esp32_chip_desc = desc
    only_cats.app.state.esp32_local_desc = desc

    try:
        client = TestClient(only_cats.app)
        resp = client.get("/health")
    finally:
        only_cats.app.state.esp32_chip_desc = None
        only_cats.app.state.esp32_local_desc = None

    assert resp.status_code == 200
    assert resp.json()["esp32_firmware"] == {
        "version": "a1b2c3d",
        "built": "Nov 20 2026 12:00:00",
        "sha256": "deadbeef",
        "local_version": "a1b2c3d",
    }


def test_health_handles_missing_esp32_firmware_descriptors():
    """Verify /health returns null firmware fields when descriptors are unavailable."""
    controller = MagicMock()
    controller.is_connected = False
    controller.lock_until = 0.0
    controller.admin_override = None

    only_cats.app.state.deps = only_cats.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
        esp32_chip_desc=None,
        esp32_local_desc=None,
    )

    client = TestClient(only_cats.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["esp32_firmware"] == {
        "version": None,
        "built": None,
        "sha256": None,
        "local_version": None,
    }
