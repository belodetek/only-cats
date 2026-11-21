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
    """Verify Pet-a-Manger button redirects when configured and hides when unset."""
    base_url, _ = live_ui_server
    target_url = config.dispenser_url

    page.route(
        f"{target_url}**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<h1>Pet-a-Manger Dispenser</h1>",
        ),
    )

    page.goto(base_url, wait_until="networkidle")
    dispenser_btn = page.get_by_role("button", name="Pet-a-Manger")
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


def test_ui_displays_esp32_firmware_version(page: Page, live_ui_server):
    """Verify Info panel renders the running ESP32 firmware short Git SHA."""
    base_url, _ = live_ui_server
    _stub_external_cdns(page, base_url)
    page.route(
        f"{base_url}/health",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status":"healthy","serial_connected":true,"model_loaded":true,'
            '"lock_engaged":false,"admin_override":null,"lockout_remaining_seconds":0.0,'
            '"esp32_firmware":{"version":"a1b2c3d","built":"Nov 20 2026 12:00:00",'
            '"sha256":"deadbeef","local_version":"a1b2c3d"}}',
        ),
    )

    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-info").click()

    expect(page.locator("#footer-meta")).to_have_text(
        "v0.0.0 · fw a1b2c3d · © belodetek 2026"
    )
    page.locator("#btn-info").click()
    fw_cell = (
        page.locator("#health-grid > div", has_text="ESP32 Firmware")
        .locator("div")
        .nth(1)
    )
    expect(fw_cell).to_have_text("a1b2c3d (deadbeef)")


def test_ui_warns_on_esp32_firmware_version_mismatch(page: Page, live_ui_server):
    """Verify ESP32 Firmware health cell turns amber when chip and local versions differ."""
    base_url, _ = live_ui_server
    _stub_external_cdns(page, base_url)
    page.route(
        f"{base_url}/health",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status":"healthy","serial_connected":true,"model_loaded":true,'
            '"lock_engaged":false,"admin_override":null,"lockout_remaining_seconds":0.0,'
            '"esp32_firmware":{"version":"old1111","built":"Nov 20 2026 12:00:00",'
            '"sha256":"deadbeef","local_version":"new2222"}}',
        ),
    )

    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-info").click()

    fw_cell = (
        page.locator("#health-grid > div", has_text="ESP32 Firmware")
        .locator("div")
        .nth(1)
    )
    expect(fw_cell).to_have_text("old1111 (deadbeef) (local: new2222)")
    expect(fw_cell).to_have_class(re.compile(r"text-amber-400"))


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1280, "height": 800},
        {"width": 390, "height": 844},
    ],
    ids=["desktop", "mobile"],
)
def test_training_dataset_triage_flow_in_browser(
    page: Page, live_ui_server, tmp_data_dirs, sample_jpeg_bytes, viewport
):
    """Verify training image browser, SVG box overlay, relabeling, and deletion."""
    base_url, _ = live_ui_server
    images_dir, labels_dir = tmp_data_dirs

    (images_dir / "capture_01.jpg").write_bytes(sample_jpeg_bytes)
    (labels_dir / "capture_01.txt").write_text("0 0.5 0.5 0.4 0.4\n", encoding="utf-8")

    page.set_viewport_size(viewport)
    _stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")

    # 1. Open dataset drawer and confirm capture count badge + thumbnail card
    expect(page.locator("#dataset-count-badge")).to_have_text("1")
    page.locator("#btn-dataset").click()
    expect(page.locator("#dataset-panel")).to_be_visible()
    card = page.locator("#dataset-grid [data-ds-idx='0']")
    expect(card).to_be_visible()

    # 2. Tap card -> opens full-screen triage modal with green Cat SVG box
    card.click()
    expect(page.locator("#triage-modal")).to_be_visible()
    svg_rect = page.locator("#triage-svg rect").first
    expect(svg_rect).to_have_attribute("stroke", "#34d399")

    # 3. Tap 'Mark Prey (1)' -> updates YOLO label on disk and turns box rose (#f43f5e)
    page.locator("#btn-label-prey").click()
    expect(svg_rect).to_have_attribute("stroke", "#f43f5e")
    assert (labels_dir / "capture_01.txt").read_text(encoding="utf-8").startswith("1 ")

    # 4. Tap 'Delete' -> removes capture, closes modal, and resets badge to 0
    page.locator("#btn-triage-delete").click()
    expect(page.locator("#triage-modal")).to_be_hidden()
    expect(page.locator("#dataset-count-badge")).to_have_text("0")
    assert not (images_dir / "capture_01.jpg").exists()


def test_interactive_bounding_box_drag_draw_and_remove_in_browser(
    page: Page, live_ui_server, tmp_data_dirs, sample_jpeg_bytes
):
    """Verify Edit Boxes mode supports dragging, drawing new boxes, and box removal."""
    base_url, _ = live_ui_server
    images_dir, labels_dir = tmp_data_dirs

    (images_dir / "edit_01.jpg").write_bytes(sample_jpeg_bytes)
    (labels_dir / "edit_01.txt").write_text(
        "0 0.500000 0.500000 0.300000 0.300000\n", encoding="utf-8"
    )

    page.set_viewport_size({"width": 390, "height": 844})
    _stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")

    page.locator("#btn-dataset").click()
    page.locator("#dataset-grid [data-ds-idx='0']").click()
    expect(page.locator("#triage-modal")).to_be_visible()

    # Enable Edit Boxes mode
    page.locator("#btn-toggle-box-edit").click()
    expect(page.locator("#box-edit-toolbar")).to_be_visible()
    expect(page.locator("#triage-svg [data-handle]")).to_have_count(4)

    # Draw a second box (Prey, class 1) in the top-left corner of the SVG
    svg_box = page.locator("#triage-svg").bounding_box()
    assert svg_box is not None
    page.mouse.move(
        svg_box["x"] + svg_box["width"] * 0.05,
        svg_box["y"] + svg_box["height"] * 0.05,
    )
    page.mouse.down()
    page.mouse.move(
        svg_box["x"] + svg_box["width"] * 0.25,
        svg_box["y"] + svg_box["height"] * 0.25,
    )
    with page.expect_response(
        lambda r: "/ui/dataset/labels/edit_01.jpg" in r.url and r.status == 200
    ):
        page.mouse.up()

    expect(page.locator("#triage-svg rect[data-box-idx]")).to_have_count(2)
    lines = (
        (labels_dir / "edit_01.txt").read_text(encoding="utf-8").strip().splitlines()
    )
    assert len(lines) == 2
    assert lines[1].startswith("1 ")

    # Remove the newly selected second box
    with page.expect_response(
        lambda r: "/ui/dataset/labels/edit_01.jpg" in r.url and r.status == 200
    ):
        page.locator("#btn-remove-selected-box").click()
    expect(page.locator("#triage-svg rect[data-box-idx]")).to_have_count(1)
    assert (
        len(
            (labels_dir / "edit_01.txt")
            .read_text(encoding="utf-8")
            .strip()
            .splitlines()
        )
        == 1
    )
