# pylint: disable=import-error
"""End-to-end browser tests for the Web UI using Playwright (Chromium)."""

import pytest
from playwright.sync_api import Page, expect


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
    expect(page.get_by_role("heading", name="iWatch uLock")).to_be_visible()
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

    # 4. Click UNLOCK -> triggers admin_unlock(), updates badge and open /health drawer
    btn_unlock.click()
    expect(page.locator("#toast")).to_contain_text("Door forced UNLOCKED")
    expect(page.locator("#status-text")).to_have_text("Unlocked (Admin)")
    expect(page.locator("#health-raw")).to_contain_text('"admin_override": "unlocked"')
    state.controller.admin_unlock.assert_called_once()

    # 5. Hide diagnostics drawer
    page.locator("#btn-close-info").click()
    expect(page.locator("#health-panel")).to_be_hidden()


def test_camera_button_navigates_to_cctv1(page: Page, live_ui_server):
    """Verify clicking the Camera button redirects the browser to /cctv1."""
    base_url, _ = live_ui_server
    _stub_external_cdns(page, base_url)

    # Intercept /cctv1 navigation target since Traefik handles /cctv1 in production
    page.route(
        f"{base_url}/cctv1*",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<html><body><h1>CCTV1 Stream</h1></body></html>",
        ),
    )

    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-camera").click()

    expect(page).to_have_url(f"{base_url}/cctv1")
    expect(page.get_by_role("heading", name="CCTV1 Stream")).to_be_visible()
