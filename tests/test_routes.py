# pylint: disable=import-error
"""Unit tests for FastAPI routes in routes.py (/webhook/reolink, /lock, /unlock, /health)."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import camera_receiver
import config
from state import AppState
from tests.conftest import assert_admin_lock_unlock_flow, bind_admin_override_mock


def _make_state() -> AppState:
    """Build an AppState with mocked controller, model, and HTTP client."""
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0
    return AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )


def test_webhook_and_health_endpoints():
    """Verify FastAPI /webhook/reolink and /health routes with mocked AppState."""
    camera_receiver.app.state.deps = _make_state()
    secret = config.webhook_secret

    with patch("routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            camera_receiver.app,
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

        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == "https://192.168.10.108"
        assert args[2]["camera_url"] == "https://192.168.10.108"
        assert args[2]["alarm_type"] == "TEST"


def test_webhook_accepts_x_webhook_secret_header():
    """Verify webhook endpoint accepts shared secret via X-Webhook-Secret header."""
    camera_receiver.app.state.deps = _make_state()

    with patch("routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            camera_receiver.app,
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
    camera_receiver.app.state.deps = _make_state()
    client = TestClient(
        camera_receiver.app,
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
    camera_receiver.app.state.deps = _make_state()
    client = TestClient(
        camera_receiver.app,
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
    camera_receiver.app.state.deps = _make_state()
    expected_url = config.camera_url

    with patch("routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            camera_receiver.app,
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

        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == expected_url
        assert args[2]["camera_url"] == expected_url


def test_webhook_ignores_non_whitelisted_alarm_types():
    """Verify webhook ignores alarm types not in config.allowed_alarm_types."""
    camera_receiver.app.state.deps = _make_state()
    secret = config.webhook_secret

    with patch("routes.fetch_and_evaluate", new_callable=AsyncMock) as mock_eval:
        client = TestClient(
            camera_receiver.app,
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
        mock_eval.assert_not_awaited()

        animal_resp = client.post(
            "/webhook/reolink",
            params={"secret": secret},
            json={"alarm": {"type": "ANIMAL"}},
        )
        assert animal_resp.status_code == 200
        assert animal_resp.json()["status"] == "queued"
        mock_eval.assert_awaited_once()


def test_admin_lock_and_unlock_endpoints():
    """Verify /lock and /unlock enforce auth, update controller state, and reflect in /health."""
    state = _make_state()
    bind_admin_override_mock(state.controller)
    camera_receiver.app.state.deps = state

    secret = config.webhook_secret
    client = TestClient(camera_receiver.app, raise_server_exceptions=False)

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
