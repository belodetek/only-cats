# pylint: disable=import-error
"""Unit tests for web_ui.py static UI delivery and admin override controls."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

import camera_receiver
import config
from tests.conftest import assert_admin_lock_unlock_flow, bind_admin_override_mock


def _make_ui_state() -> camera_receiver.AppState:
    """Create a mocked AppState for Web UI endpoint testing."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    controller.admin_override = None
    return camera_receiver.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )


def test_ui_root_serves_html_and_static_assets():
    """Verify GET / returns the web UI HTML and /static assets are reachable."""
    camera_receiver.app.state.deps = _make_ui_state()
    client = TestClient(camera_receiver.app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "onlyCat(s)" in resp.text
    assert "/static/logo.png" in resp.text
    assert "/static/app.js" in resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "/cctv1" in js_resp.text

    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200

    logo_resp = client.get("/static/logo.png")
    assert logo_resp.status_code == 200


def test_ui_lock_and_unlock_endpoints():
    """Verify POST /ui/lock and /ui/unlock toggle persistent admin override."""
    state = _make_ui_state()
    bind_admin_override_mock(state.controller)
    camera_receiver.app.state.deps = state

    client = TestClient(camera_receiver.app)
    assert_admin_lock_unlock_flow(
        client=client,
        controller=state.controller,
        lock_url="/ui/lock",
        unlock_url="/ui/unlock",
    )


def test_ui_config_returns_dispenser_url(monkeypatch):
    """Verify /ui/config exposes configured dispenser_url without hardcoding."""
    client = TestClient(camera_receiver.app)

    resp_default = client.get("/ui/config")
    assert resp_default.status_code == 200
    assert resp_default.json() == {"dispenser_url": "https://dispenser.local.test/"}

    monkeypatch.setattr(config, "dispenser_url", "")
    resp_empty = client.get("/ui/config")
    assert resp_empty.status_code == 200
    assert resp_empty.json() == {"dispenser_url": ""}
