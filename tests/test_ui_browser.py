# pylint: disable=import-error
"""End-to-end browser tests for the Web UI using Playwright (Chromium)."""

import re

import pytest
from playwright.sync_api import Page, expect

import config


def _stub_external_cdns(page: Page, base_url: str) -> None:
    """Fulfill external CDN scripts immediately so tests work offline and deterministically."""
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


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1280, "height": 800},  # Desktop Chrome
        {"width": 390, "height": 844},  # Mobile Chrome (Pixel / iPhone size)
    ],
    ids=["desktop", "mobile"],
)
def test_ui_renders_and_buttons_work_in_browser(page: Page, live_ui_server, viewport):
    """Verify UI renders across desktop/mobile viewports and all 4 buttons function."""
    base_url, state = live_ui_server
    page.set_viewport_size(viewport)
    _stub_external_cdns(page, base_url)

    page.goto(f"{base_url}/", wait_until="networkidle")

    # 1. Verify header, logo, initial badge, and all 4 buttons are visible
    expect(page.get_by_role("heading", name="onlyCat(s)")).to_be_visible()
    expect(page.locator("img[src='/static/logo.png']")).to_be_visible()
    expect(page.locator("#status-text")).to_have_text("Unlocked")

    btn_lock = page.locator("#btn-lock")
    btn_unlock = page.locator("#btn-unlock")
    btn_info = page.locator("#btn-info")
    btn_camera = page.locator("#btn-camera")

    expect(btn_lock).to_be_visible()
    expect(btn_unlock).to_be_visible()
    expect(btn_info).to_be_visible()
    expect(btn_camera).to_be_visible()

    # 2. Click LOCK -> triggers admin_lock(), shows toast, updates status badge
    btn_lock.click()
    expect(page.locator("#toast")).to_contain_text("Door forced LOCKED")
    expect(page.locator("#status-text")).to_have_text("Locked (Admin)")
    state.controller.admin_lock.assert_called_once()

    # 3. Click INFO -> fetches /health and reveals diagnostics drawer
    expect(page.locator("#health-panel")).to_be_hidden()
    btn_info.click()
    expect(page.locator("#health-panel")).to_be_visible()
    expect(page.locator("#health-raw")).to_contain_text('"admin_override": "locked"')
    expect(page.locator("#health-grid")).to_contain_text("Connected")
    service_cell = (
        page.locator("#health-grid > div", has_text="Service Status")
        .locator("div")
        .nth(1)
    )
    expect(service_cell).to_have_text("healthy")
    expect(service_cell).to_have_class(re.compile(r"text-emerald-400"))

    # 4. Click UNLOCK -> triggers admin_unlock(), updates badge and open /health drawer
    btn_unlock.click()
    expect(page.locator("#toast")).to_contain_text("Door forced UNLOCKED")
    expect(page.locator("#status-text")).to_have_text("Unlocked (Admin)")
    expect(page.locator("#health-raw")).to_contain_text('"admin_override": "unlocked"')
    state.controller.admin_unlock.assert_called_once()

    # 5. Hide diagnostics drawer
    page.locator("#btn-close-info").click()
    expect(page.locator("#health-panel")).to_be_hidden()

    # 6. Verify footer rendering
    expect(page.locator("#footer-meta")).to_contain_text("v0.0.0 · © belodetek 2026")
    repo_link = page.locator("#footer-repo-link")
    expect(repo_link).to_be_visible()
    expect(repo_link).to_have_attribute(
        "href", "https://github.com/belodetek/only-cats"
    )


def test_camera_button_navigates_to_cctv1(page: Page, live_ui_server):
    """Verify clicking the Camera button redirects the browser to /cctv1/."""
    base_url, _ = live_ui_server
    _stub_external_cdns(page, base_url)

    # Intercept /cctv1/ navigation target since Traefik handles /cctv1 in production
    page.route(
        f"{base_url}/cctv1**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<html><body><h1>CCTV1 Stream</h1></body></html>",
        ),
    )

    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-camera").click()

    expect(page).to_have_url(f"{base_url}/cctv1/")
    expect(page.get_by_role("heading", name="CCTV1 Stream")).to_be_visible()


@pytest.mark.parametrize("target_key", ["domain_https", "balena_http"])
def test_traefik_routes_ui_and_camera_end_to_end(
    browser, traefik_ui_server, target_key
):
    """Verify Traefik routes /, /ui/lock, /ui/unlock, and /cctv1 on both hostnames."""
    base_url = traefik_ui_server[target_key]
    state = traefik_ui_server["state"]

    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    _stub_external_cdns(page, base_url)

    # 1. Load UI through Traefik
    page.goto(f"{base_url}/", wait_until="networkidle")
    expect(page.get_by_role("heading", name="onlyCat(s)")).to_be_visible()

    # 2. Lock & Unlock buttons traverse Traefik -> oauth2-auth -> FastAPI
    page.locator("#btn-lock").click()
    expect(page.locator("#status-text")).to_have_text("Locked (Admin)")
    state.controller.admin_lock.assert_called_once()

    page.locator("#btn-unlock").click()
    expect(page.locator("#status-text")).to_have_text("Unlocked (Admin)")
    state.controller.admin_unlock.assert_called_once()

    # 3. Camera button redirects /cctv1 -> /cctv1/ -> StripPrefix -> mock-camera
    page.locator("#btn-camera").click()
    expect(page).to_have_url(f"{base_url}/cctv1/")
    expect(page.get_by_role("heading", name="Mock Camera (/)")).to_be_visible()

    context.close()


def test_traefik_auth_and_webhook_routing(browser, traefik_ui_server):
    """Verify Traefik blocks unauthenticated UI calls while allowing /webhook/reolink."""
    domain_https = traefik_ui_server["domain_https"]
    domain_http = traefik_ui_server["domain_http"]

    # 1. HTTP on DOMAIN_NAME redirects 308/301 to HTTPS
    ctx_http = browser.new_context(ignore_https_errors=True)
    resp_http = ctx_http.request.get(f"{domain_http}/", max_redirects=0)
    assert resp_http.status in (301, 308)
    assert resp_http.headers["location"].startswith("https://iwatch.local.test/")
    ctx_http.close()

    # 2. Unauthenticated UI request is rejected by oauth2-auth forwardAuth
    ctx_unauth = browser.new_context(
        ignore_https_errors=True,
        extra_http_headers={"X-Test-Unauth": "1"},
    )
    unauth_resp = ctx_unauth.request.post(f"{domain_https}/ui/lock")
    assert unauth_resp.status == 401

    # 3. Webhook on DOMAIN_NAME bypasses oauth2-auth and hits FastAPI secret check
    webhook_resp = ctx_unauth.request.post(
        f"{domain_https}/webhook/reolink",
        data={"alarm": {"type": "ANIMAL"}},
    )
    assert webhook_resp.status == 401
    assert "Invalid webhook secret" in webhook_resp.text()
    ctx_unauth.close()


def test_dispenser_button_visibility_and_redirect(page, live_ui_server, monkeypatch):
    """Verify Pret-a-Manger button redirects when configured and hides when unset."""
    base_url, _ = live_ui_server
    target_url = config.dispenser_url

    page.route(
        f"{target_url}**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<h1>Pret-a-Manger Dispenser</h1>",
        ),
    )

    page.goto(base_url, wait_until="networkidle")
    dispenser_btn = page.get_by_role("button", name="Pret-a-Manger")
    expect(dispenser_btn).to_be_visible()
    dispenser_btn.click()
    expect(page).to_have_url(target_url)

    monkeypatch.setattr(config, "dispenser_url", "")
    page.goto(base_url, wait_until="networkidle")
    expect(dispenser_btn).to_be_hidden()


def test_esp32_disconnected_disables_controls_and_highlights_health(
    page: Page, live_ui_server
):
    """Verify disconnected ESP32 disables lock/unlock buttons, dims open badge,
    and yellows health."""
    base_url, state = live_ui_server
    state.controller.is_connected = False
    _stub_external_cdns(page, base_url)

    page.goto(f"{base_url}/", wait_until="networkidle")

    expect(page.locator("#btn-lock")).to_be_disabled()
    expect(page.locator("#btn-unlock")).to_be_disabled()
    expect(page.locator("#status-text")).to_have_text("Disabled (Open)")
    expect(page.locator("#status-badge")).to_have_class(re.compile(r"opacity-75"))

    page.locator("#btn-info").click()
    esp_cell = (
        page.locator("#health-grid > div", has_text="ESP32 Serial")
        .locator("div")
        .nth(1)
    )
    expect(esp_cell).to_have_text("Disconnected")
    expect(esp_cell).to_have_class(re.compile(r"text-amber-400"))
