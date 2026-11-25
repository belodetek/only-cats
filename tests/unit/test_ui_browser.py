# pylint: disable=import-error
"""End-to-end browser tests for the Web UI using Playwright (Chromium)."""

import re

import pytest
from playwright.sync_api import Page, expect

import config
import dataset
import metrics
from tests.conftest import (
    TRAEFIK_UPSTREAM_FILE,
    _patch_metrics_store,
    open_first_dataset_triage_modal,
    stub_external_cdns,
    write_traefik_upstream,
)


def _assert_security_headers(headers: dict[str, str]) -> None:
    """Verify anti-clickjacking, CSP, and MIME-sniffing response headers."""
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "same-origin"
    csp = headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


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
    stub_external_cdns(page, base_url)

    resp = page.goto(f"{base_url}/", wait_until="networkidle")
    assert resp is not None
    _assert_security_headers(resp.headers)

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

    # 6. Verify footer rendering (includes app version and optional model date)
    expect(page.locator("#footer-meta")).to_contain_text("v0.0.0 ·")
    expect(page.locator("#footer-meta")).to_contain_text("© belodetek 2026")
    repo_link = page.locator("#footer-repo-link")
    expect(repo_link).to_be_visible()
    expect(repo_link).to_have_attribute(
        "href", "https://github.com/belodetek/only-cats"
    )


def test_camera_button_navigates_to_cctv1(page: Page, live_ui_server):
    """Verify clicking the Camera button redirects the browser to /cctv1/."""
    base_url, _ = live_ui_server
    stub_external_cdns(page, base_url)

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
    stub_external_cdns(page, base_url)

    # 1. Load UI through Traefik and confirm security headers are enforced
    resp = page.goto(f"{base_url}/", wait_until="networkidle")
    assert resp is not None
    _assert_security_headers(resp.headers)
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
    unauth_resp = ctx_unauth.request.post(
        f"{domain_https}/ui/lock",
        headers={"X-Requested-With": "fetch"},
    )
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
    stub_external_cdns(page, base_url)

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


def test_ui_displays_esp32_firmware_and_model_metadata(page: Page, live_ui_server):
    """Verify Info panel and footer render ESP32 firmware SHA and OpenVINO model date/version."""
    base_url, _ = live_ui_server
    stub_external_cdns(page, base_url)
    page.route(
        f"{base_url}/health",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status":"healthy","serial_connected":true,"model_loaded":true,'
            '"model_metadata":{"version":"8.4.218","date":"2026-11-25T12:21:45.531191-07:00",'
            '"short_date":"2026-11-25","task":"detect","imgsz":[1280,1280]},'
            '"lock_engaged":false,"admin_override":null,"lockout_remaining_seconds":0.0,'
            '"esp32_firmware":{"version":"a1b2c3d","built":"Nov 20 2026 12:00:00",'
            '"sha256":"deadbeef","local_version":"a1b2c3d"}}',
        ),
    )

    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-info").click()

    expect(page.locator("#footer-meta")).to_have_text(
        "v0.0.0 · fw a1b2c3d · model 2026-11-25 · © belodetek 2026"
    )
    fw_cell = (
        page.locator("#health-grid > div", has_text="ESP32 Firmware")
        .locator("div")
        .nth(1)
    )
    expect(fw_cell).to_have_text("a1b2c3d (deadbeef)")

    model_cell = (
        page.locator("#health-grid > div", has_text="YOLO Model").locator("div").nth(1)
    )
    expect(model_cell).to_have_text("Loaded (v8.4.218 · 2026-11-25)")


def test_ui_warns_on_esp32_firmware_version_mismatch(page: Page, live_ui_server):
    """Verify ESP32 Firmware health cell turns amber when chip and local versions differ."""
    base_url, _ = live_ui_server
    stub_external_cdns(page, base_url)
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
    """Verify training image browser, SVG box overlay, relabeling to Prey (0), and deletion."""
    base_url, _ = live_ui_server
    images_dir, labels_dir = tmp_data_dirs

    # Seed an unlabeled capture (0 boxes) so relabeling to Prey (0) creates a class-0 box
    (images_dir / "capture_01.jpg").write_bytes(sample_jpeg_bytes)
    (labels_dir / "capture_01.txt").write_text("", encoding="utf-8")

    page.set_viewport_size(viewport)
    stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")

    # 1. Open dataset drawer and confirm capture count badge + thumbnail card
    expect(page.locator("#dataset-count-badge")).to_have_text("1")
    page.locator("#btn-dataset").click()
    expect(page.locator("#dataset-panel")).to_be_visible()
    card = page.locator("#dataset-grid [data-ds-idx='0']")
    expect(card).to_be_visible()

    # 2. Tap card -> opens full-screen triage modal with 0 initial boxes
    card.click()
    expect(page.locator("#triage-modal")).to_be_visible()
    expect(page.locator("#triage-svg rect")).to_have_count(0)

    # 3. Tap 'Prey (0)' -> writes class 0 label on disk and renders rose (#f43f5e) SVG box
    page.locator("#btn-label-prey").click()
    svg_rect = page.locator("#triage-svg rect").first
    expect(svg_rect).to_have_attribute("stroke", "#f43f5e")
    assert (labels_dir / "capture_01.txt").read_text(encoding="utf-8").startswith("0 ")

    # 4. Tap 'Delete Image' -> removes capture, closes modal, and resets badge to 0
    page.locator("#btn-triage-delete").click()
    expect(page.locator("#triage-modal")).to_be_hidden()
    expect(page.locator("#dataset-count-badge")).to_have_text("0")
    assert not (images_dir / "capture_01.jpg").exists()


def test_interactive_bounding_box_drag_draw_and_remove_in_browser(
    page: Page, live_ui_server, tmp_data_dirs, sample_jpeg_bytes
):
    """Verify Edit Boxes mode supports dragging, drawing new Prey (0) boxes, and box removal."""
    base_url, _ = live_ui_server
    images_dir, labels_dir = tmp_data_dirs

    (images_dir / "edit_01.jpg").write_bytes(sample_jpeg_bytes)
    (labels_dir / "edit_01.txt").write_text(
        "0 0.500000 0.500000 0.300000 0.300000\n", encoding="utf-8"
    )

    page.set_viewport_size({"width": 390, "height": 844})
    stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")

    open_first_dataset_triage_modal(page)

    # Enable Edit Boxes mode
    page.locator("#btn-toggle-box-edit").click()
    expect(page.locator("#box-edit-toolbar")).to_be_visible()
    expect(page.locator("#triage-svg [data-handle]")).to_have_count(4)

    # Draw a second box (Prey, class 0) in the top-left corner of the SVG
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
    assert lines[1].startswith("0 ")

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


def test_triage_pagination_shows_spinner_and_locks_buttons_while_loading(
    page: Page, live_ui_server, tmp_data_dirs, sample_jpeg_bytes
):
    """Verify Prev/Next buttons disable and spinner shows until next image loads."""
    base_url, _ = live_ui_server
    images_dir, _ = tmp_data_dirs

    (images_dir / "img_01.jpg").write_bytes(sample_jpeg_bytes)
    (images_dir / "img_02.jpg").write_bytes(sample_jpeg_bytes)

    stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-dataset").click()
    page.locator("#dataset-grid [data-ds-idx='0']").click()
    expect(page.locator("#triage-loading")).to_be_hidden()

    # Hold the second full-res image response to inspect in-flight loading state
    release_image = []

    def _hold_second_image(route):
        if "thumb=1" in route.request.url:
            route.continue_()
            return
        release_image.append(route)

    page.route(f"{base_url}/ui/dataset/image/*", _hold_second_image)
    page.locator("#btn-triage-next").click()

    expect(page.locator("#triage-loading")).to_be_visible()
    expect(page.locator("#btn-triage-prev")).to_be_disabled()
    expect(page.locator("#btn-triage-next")).to_be_disabled()

    release_image[0].continue_()
    expect(page.locator("#triage-loading")).to_be_hidden()
    expect(page.locator("#btn-triage-prev")).to_be_enabled()


def test_traefik_renders_friendly_502_page_when_backend_down(
    browser, traefik_ui_server
):
    """Verify Traefik serves friendly static error.html with 502 status when backend is down."""
    original = (
        TRAEFIK_UPSTREAM_FILE.read_text(encoding="utf-8")
        if TRAEFIK_UPSTREAM_FILE.exists()
        else None
    )
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    try:
        write_traefik_upstream("http://127.0.0.1:59999")
        page.wait_for_timeout(1200)  # allow Traefik file watcher to reload

        resp = page.goto(
            f"{traefik_ui_server['domain_https']}/", wait_until="domcontentloaded"
        )
        assert resp is not None
        assert resp.status == 502
        expect(page.locator("#err-code")).to_have_text("502")
        expect(page.locator("#err-title")).to_have_text("Bad Gateway")
    finally:
        if original is not None:
            TRAEFIK_UPSTREAM_FILE.write_text(original, encoding="utf-8")
            for _ in range(25):
                probe = page.request.get(f"{traefik_ui_server['balena_http']}/health")
                if probe.status == 200:
                    break
                page.wait_for_timeout(200)
        context.close()


def test_metrics_drawer_opens_and_renders_telemetry(page, live_ui_server):
    """Verify clicking Metrics button opens the telemetry drawer and loads /ui/metrics."""
    base_url, _ = live_ui_server
    page.goto(base_url, wait_until="networkidle")
    drawer = page.locator("#telemetry-drawer")
    expect(drawer).to_be_hidden()

    page.locator("#btn-drawer").click()
    expect(drawer).to_be_visible()

    grid = page.locator("#drawer-metrics-grid")
    expect(grid).to_contain_text("Total Locks")
    expect(grid).to_contain_text("Total Unlocks")
    expect(grid).to_contain_text("Prey Triggers")

    page.locator("#btn-close-drawer").click()
    expect(drawer).to_be_hidden()


def test_metrics_drawer_visualizes_populated_telemetry(
    page, live_ui_server, monkeypatch
):
    """Verify populated locks, durations, hourly bars, and prey detections render in UI."""
    store = metrics.MetricsStore()

    # Seed 2 completed locks of different durations (<15s and 1-5m)
    store.record_lock(source="prey_detection")
    with store._lock:  # pylint: disable=protected-access
        store._active_lock_start -= 8.0  # pylint: disable=protected-access
    store.record_unlock(source="expiry")

    store.record_lock(source="admin_ui")
    with store._lock:  # pylint: disable=protected-access
        store._active_lock_start -= 120.0  # pylint: disable=protected-access
    store.record_unlock(source="admin_ui")

    # Seed prey detections
    store.record_prey_detection([("prey", 0.94)], is_test=False)
    store.record_prey_detection([("mouse", 0.86)], is_test=False)

    _patch_metrics_store(monkeypatch, store)

    base_url, _ = live_ui_server
    page.goto(base_url, wait_until="networkidle")
    page.locator("#btn-drawer").click()

    drawer = page.locator("#telemetry-drawer")
    expect(drawer).to_be_visible()

    # 1. Verify KPI cards reflect seeded totals
    grid = page.locator("#drawer-metrics-grid")
    expect(grid).to_contain_text("Total Locks")
    expect(grid).to_contain_text("2")
    expect(grid).to_contain_text("Prey Triggers")

    # 2. Verify 24-hour distribution chart rendered 24 hour columns
    hourly_chart = page.locator("#drawer-hourly-chart")
    expect(hourly_chart.locator("> div")).to_have_count(24)

    # 3. Verify lock duration distribution renders buckets
    buckets_list = page.locator("#drawer-buckets-list")
    expect(buckets_list).to_contain_text("<15s")
    expect(buckets_list).to_contain_text("1-5m")

    # 4. Verify recent lock & detection feeds render seeded events
    recent_locks = page.locator("#drawer-recent-locks")
    expect(recent_locks).to_contain_text("prey_detection")
    expect(recent_locks).to_contain_text("admin_ui")

    recent_detections = page.locator("#drawer-recent-detections")
    expect(recent_detections).to_contain_text("94%")


def test_dataset_browser_overlays_json_metadata_on_thumbnails_and_triage(
    page: Page, live_ui_server, sample_jpeg_bytes
):
    """Verify .json metadata renders on dataset thumbnails and in #triage-meta-bar."""
    base_url, _ = live_ui_server
    dataset.save_clean_capture(
        stem="prey_20261122_101500_meta",
        raw_image_bytes=sample_jpeg_bytes,
        boxes=[dataset.YoloBox(cls=0, x=0.5, y=0.5, w=0.3, h=0.3)],
        meta={
            "timestamp_utc": "2026-11-22T17:15:00+00:00",
            "event_type": "ANIMAL",
            "lock_engaged": True,
            "lockout_duration_sec": 180,
            "fetch_ms": 38.4,
            "infer_ms": 21.2,
            "detections": [{"class": "prey", "confidence": 0.93}],
        },
    )

    stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.locator("#btn-dataset").click()

    dataset_panel = page.locator("#dataset-panel")
    expect(dataset_panel).to_be_visible()

    meta_pill = dataset_panel.locator(".ds-meta-pill").first
    expect(meta_pill).to_be_visible()
    expect(meta_pill).to_have_text("ANIMAL · 93%")

    dataset_panel.locator("[data-ds-idx='0']").click()

    triage_modal = page.locator("#triage-modal")
    expect(triage_modal).to_be_visible()

    meta_bar = page.locator("#triage-meta-bar")
    expect(meta_bar).to_be_visible()
    expect(meta_bar).to_contain_text("ANIMAL")
    expect(meta_bar).to_contain_text("fetch 38.4ms")
    expect(meta_bar).to_contain_text("infer 21.2ms")
    expect(meta_bar).to_contain_text("Locked (180s)")
    expect(meta_bar).to_contain_text("YOLO: prey 93%")

    meta_json = page.locator("#triage-meta-json")
    expect(meta_json).to_be_hidden()
    page.locator("#btn-toggle-meta-json").click()
    expect(meta_json).to_be_visible()
    expect(meta_json).to_contain_text('"event_type": "ANIMAL"')


def test_dataset_purge_modal_requires_delete_confirmation_in_browser(
    page: Page, live_ui_server, tmp_data_dirs, sample_jpeg_bytes
):
    """Verify Purge button opens modal, enforces typing 'DELETE', and purges dataset."""
    base_url, _ = live_ui_server
    images_dir, labels_dir = tmp_data_dirs

    dataset.save_clean_capture(
        stem="prey_20261125_120000_purge",
        raw_image_bytes=sample_jpeg_bytes,
        boxes=[dataset.YoloBox(cls=0, x=0.5, y=0.5, w=0.2, h=0.2)],
        meta={"event_type": "ANIMAL"},
    )

    stub_external_cdns(page, base_url)
    page.goto(f"{base_url}/", wait_until="networkidle")

    expect(page.locator("#dataset-count-badge")).to_have_text("1")
    page.locator("#btn-dataset").click()
    expect(page.locator("#dataset-panel")).to_be_visible()

    purge_btn = page.locator("#btn-purge-dataset")
    expect(purge_btn).to_be_enabled()
    purge_btn.click()

    purge_modal = page.locator("#purge-modal")
    confirm_input = page.locator("#purge-confirm-input")
    confirm_submit = page.locator("#btn-confirm-purge")

    expect(purge_modal).to_be_visible()
    expect(confirm_submit).to_be_disabled()

    # Lowercase or partial input keeps confirmation button disabled
    confirm_input.fill("delete")
    expect(confirm_submit).to_be_disabled()

    # Exact "DELETE" enables confirmation button and purges files on click
    confirm_input.fill("DELETE")
    expect(confirm_submit).to_be_enabled()
    confirm_submit.click()

    expect(purge_modal).to_be_hidden()
    expect(page.locator("#dataset-count-badge")).to_have_text("0")
    expect(purge_btn).to_be_disabled()
    expect(page.locator("#toast")).to_contain_text("Purged 1 images")
    assert not list(images_dir.iterdir())
    assert not list(labels_dir.iterdir())
