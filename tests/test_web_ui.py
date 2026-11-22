"""Unit tests for web_ui.py static UI delivery and admin override controls."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlsplit

# pylint: disable=import-error
from fastapi.testclient import TestClient

# pylint: enable=import-error
import config
import only_cats
from tests.conftest import assert_admin_lock_unlock_flow, bind_admin_override_mock


def _make_ui_state() -> only_cats.AppState:
    """Create a mocked AppState for Web UI endpoint testing."""
    controller = MagicMock()
    controller.is_connected = True
    controller.lock_until = 0.0
    controller.admin_override = None
    return only_cats.AppState(
        controller=controller,
        model=MagicMock(),
        http_client=AsyncMock(),
    )


def test_ui_config_returns_dispenser_url_and_version(monkeypatch):
    """Verify /ui/config exposes stripped dispenser_url, app_version, and repo_url."""
    client = TestClient(only_cats.app)

    parsed = urlsplit(config.dispenser_url)
    expected_root = f"{parsed.scheme}://{parsed.netloc}/"

    resp_default = client.get("/ui/config")
    assert resp_default.status_code == 200
    assert resp_default.json() == {
        "dispenser_url": expected_root,
        "app_version": "0.0.0",
        "repo_url": "https://github.com/belodetek/only-cats",
    }

    monkeypatch.setattr(config, "dispenser_url", "")
    monkeypatch.setattr(config, "app_version", "1.2.3")
    monkeypatch.setattr(config, "repo_url", "")
    resp_custom = client.get("/ui/config")
    assert resp_custom.status_code == 200
    assert resp_custom.json() == {
        "dispenser_url": "",
        "app_version": "1.2.3",
        "repo_url": "",
    }


def test_ui_root_serves_html_and_static_assets():
    """Verify GET / returns the web UI HTML and /static assets are reachable."""
    only_cats.app.state.deps = _make_ui_state()
    client = TestClient(only_cats.app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "onlyCat(s)" in resp.text
    assert "/static/logo.png" in resp.text
    assert "/static/app.js" in resp.text
    assert 'id="triage-meta-bar"' in resp.text
    assert 'id="btn-drawer"' in resp.text
    assert 'id="telemetry-drawer"' in resp.text
    assert 'href="/metrics"' in resp.text

    # Versioned static asset gets immutable Cache-Control + gzip compression
    js_resp = client.get(
        "/static/app.js?v=test123",
        headers={"Accept-Encoding": "gzip"},
    )
    assert js_resp.status_code == 200
    assert js_resp.headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert js_resp.headers.get("content-encoding") == "gzip"

    # Unversioned asset (e.g. /static/logo.png without ?v=) is not marked immutable
    logo_resp = client.get("/static/logo.png")
    assert logo_resp.status_code == 200
    assert "immutable" not in logo_resp.headers.get("cache-control", "")


def test_ui_lock_and_unlock_endpoints():
    """Verify POST /ui/lock and /ui/unlock toggle persistent admin override."""
    state = _make_ui_state()
    bind_admin_override_mock(state.controller)
    only_cats.app.state.deps = state

    client = TestClient(only_cats.app)
    assert_admin_lock_unlock_flow(
        client=client,
        controller=state.controller,
        lock_url="/ui/lock",
        unlock_url="/ui/unlock",
    )


def test_friendly_html_404_for_browsers_and_json_for_api():
    """Verify browsers receive friendly HTML 404 while API clients still get JSON."""
    client = TestClient(only_cats.app)

    html_resp = client.get("/nonexistent-page", headers={"Accept": "text/html"})
    assert html_resp.status_code == 404
    assert "text/html" in html_resp.headers["content-type"]
    assert "404" in html_resp.text
    assert 'id="refresh-btn"' in html_resp.text
    assert "Refresh" in html_resp.text

    json_resp = client.get("/nonexistent-page", headers={"Accept": "application/json"})
    assert json_resp.status_code == 404
    assert json_resp.json() == {"detail": "Not Found"}


def test_csrf_blocks_cross_origin_and_headerless_ui_posts():
    """Verify state-changing /ui/* endpoints reject cross-origin or headerless POSTs."""
    client = TestClient(only_cats.app)

    # 1. Bare form POST without X-Requested-With -> 403
    no_header = client.post("/ui/lock")
    assert no_header.status_code == 403

    # 2. Cross-origin fetch with mismatched Origin -> 403
    bad_origin = client.post(
        "/ui/unlock",
        headers={
            "Host": "iwatch.local.test",
            "Origin": "https://evil.example.com",
            "X-Requested-With": "fetch",
        },
    )
    assert bad_origin.status_code == 403
