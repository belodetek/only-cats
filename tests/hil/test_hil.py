"""Hardware-in-the-Loop (HiL) tests."""

import time
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import httpx
import pytest
from playwright.sync_api import Page, expect

# pylint: enable=import-error
import config
from tests.conftest import (
    HIL_APP_URL,
    HIL_EMU_URL,
    open_first_dataset_triage_modal,
    stub_external_cdns,
    trigger_camera_webhook,
)

HIL_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = HIL_DIR / "fixtures"

pytestmark = pytest.mark.hil


def _wait_for_serial_line(substring: str, timeout: float = 8.0) -> dict[str, Any]:
    """Poll the QEMU PTY tee proxy until a matching serial event is recorded."""
    deadline = time.monotonic() + timeout
    last_events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        resp = httpx.get(f"{HIL_EMU_URL}/serial/history", timeout=2.0)
        resp.raise_for_status()
        last_events = resp.json().get("events", [])
        for ev in last_events:
            if substring in ev.get("line", "") or substring in ev.get("raw", ""):
                return ev
        time.sleep(0.1)
    raise AssertionError(
        f"Timed out waiting for serial event containing {substring!r}. "
        f"Recent events: {last_events[-10:]}"
    )


def _wait_for_app_serial_connected(
    expected: bool = True, timeout: float = 20.0
) -> dict[str, Any]:
    """Poll /health until serial_connected matches expected state."""
    deadline = time.monotonic() + timeout
    last_health: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{HIL_APP_URL}/health", timeout=2.0)
            if resp.status_code == 200:
                last_health = resp.json()
                if bool(last_health.get("serial_connected")) is expected:
                    return last_health
        except httpx.RequestError:
            pass
        time.sleep(0.2)
    raise AssertionError(
        f"Timed out waiting for serial_connected={expected}. Last /health: {last_health}"
    )


@pytest.fixture(scope="session", autouse=True)
def _verify_hil_services_ready() -> None:
    """Confirm all dependent services are ready and warm up OpenVINO inference."""
    last_status: dict[str, Any] = {}
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        for name, url in (
            ("app", f"{HIL_APP_URL}/health"),
            ("emu", f"{HIL_EMU_URL}/health"),
            ("cam", f"{config.camera_url}/health"),
        ):
            try:
                resp = httpx.get(url, timeout=2.0)
                last_status[name] = (
                    resp.json() if resp.status_code == 200 else resp.status_code
                )
            except httpx.RequestError as exc:
                last_status[name] = repr(exc)

        app_ok = (
            isinstance(last_status.get("app"), dict)
            and last_status["app"].get("serial_connected") is True
        )
        emu_ok = isinstance(last_status.get("emu"), dict)
        cam_ok = isinstance(last_status.get("cam"), dict)
        if app_ok and emu_ok and cam_ok:
            # Warm up OpenVINO CPU graph compilation on empty.jpg (no lock)
            httpx.post(
                f"{config.camera_url}/stage/empty.jpg", timeout=3.0
            ).raise_for_status()
            trigger_camera_webhook("ANIMAL")
            time.sleep(8.0)
            httpx.post(f"{HIL_EMU_URL}/serial/clear", timeout=3.0).raise_for_status()
            return
        time.sleep(0.25)

    raise RuntimeError(f"Timed out waiting for services: {last_status}")


@pytest.fixture(autouse=True)
def _reset_hil_state_between_tests():
    """Clear serial history before each HiL test."""
    httpx.post(f"{HIL_EMU_URL}/serial/clear", timeout=3.0).raise_for_status()
    yield


def test_real_firmware_handshake_and_health_endpoint():
    """Verify only-cats connects to QEMU ESP32-C6 and reports healthy serial & model."""
    health = httpx.get(f"{HIL_APP_URL}/health", timeout=5.0).json()
    assert health["serial_connected"] is True
    assert health["model_loaded"] is True


def test_test_webhook_triggers_real_esp32_lock_ack_and_updates_ui(page: Page):
    """Verify TEST webhook -> b'L' over PTY -> QEMU firmware ACK:L -> UI badge."""
    httpx.post(f"{config.camera_url}/stage/empty.jpg", timeout=3.0).raise_for_status()

    wh_resp = trigger_camera_webhook("TEST")
    assert wh_resp["status_code"] == 200

    _wait_for_serial_line("L", timeout=10.0)
    _wait_for_serial_line("ACK:L", timeout=10.0)

    try:
        stub_external_cdns(page, HIL_APP_URL)
        page.goto(f"{HIL_APP_URL}/", wait_until="networkidle")
        expect(page.locator("#status-text")).to_have_text("Locked (Prey)")
    finally:
        _wait_for_serial_line(
            "EVENT:TIMEOUT_UNLOCK", timeout=config.lockout_duration_sec + 6.0
        )

    page.reload(wait_until="networkidle")
    expect(page.locator("#status-text")).to_have_text("Unlocked")


def test_prey_fixture_triggers_yolo_esp32_lock_and_persists_dataset(page: Page):
    """Stage prey.jpg -> ANIMAL webhook -> YOLO 0:prey -> ESP32 lock -> UI dataset & metadata."""
    prey_fixture = FIXTURES_DIR / "prey.jpg"
    if not prey_fixture.is_file():
        pytest.skip(f"Missing prey test fixture at {prey_fixture}")

    httpx.post(f"{config.camera_url}/stage/prey.jpg", timeout=3.0).raise_for_status()

    wh_resp = trigger_camera_webhook("ANIMAL")
    assert wh_resp["status_code"] == 200

    # 1. Verify real ESP32-C6 firmware locked the solenoid
    _wait_for_serial_line("L", timeout=15.0)
    _wait_for_serial_line("ACK:L", timeout=10.0)

    try:
        # 2. Verify capture, class-0 prey label, and sidecar metadata were persisted
        items: list[dict[str, Any]] = []
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            items_resp = httpx.get(
                f"{HIL_APP_URL}/ui/dataset/items?filter=prey", timeout=5.0
            )
            items_resp.raise_for_status()
            items = items_resp.json().get("items", [])
            if items:
                break
            time.sleep(0.1)
        assert len(items) >= 1
        latest = items[0]
        assert latest["has_prey"] is True
        assert any(box["cls"] == 0 for box in latest["boxes"])
        assert latest["meta"].get("event_type") == "ANIMAL"

        # 3. Verify capture, SVG box, and Meta JSON render in the live Web UI
        stub_external_cdns(page, HIL_APP_URL)
        page.goto(f"{HIL_APP_URL}/", wait_until="networkidle")
        open_first_dataset_triage_modal(page)
        expect(page.locator("#triage-svg rect").first).to_have_attribute(
            "stroke", "#f43f5e"
        )
        expect(page.locator("#triage-meta-bar")).to_contain_text("ANIMAL")

        page.locator("#btn-toggle-meta-json").click()
        expect(page.locator("#triage-meta-json")).to_be_visible()
        expect(page.locator("#triage-meta-json")).to_contain_text(
            '"event_type": "ANIMAL"'
        )
    finally:
        # Ensure lockout expires so subsequent tests start unlocked
        _wait_for_serial_line(
            "EVENT:TIMEOUT_UNLOCK", timeout=config.lockout_duration_sec + 6.0
        )


def test_empty_fixture_does_not_lock_and_persists_training_pair():
    """Stage empty.jpg -> ANIMAL webhook -> 0 detections -> no lock -> train_* persisted."""
    empty_fixture = FIXTURES_DIR / "empty.jpg"
    if not empty_fixture.is_file():
        pytest.skip(f"Missing empty test fixture at {empty_fixture}")

    httpx.post(f"{config.camera_url}/stage/empty.jpg", timeout=3.0).raise_for_status()

    wh_resp = trigger_camera_webhook("ANIMAL")
    assert wh_resp["status_code"] == 200

    # Wait briefly for inference pipeline to complete
    time.sleep(1.5)

    # Confirm no lock command was sent to the ESP32-C6
    events = (
        httpx.get(f"{HIL_EMU_URL}/serial/history", timeout=3.0).json().get("events", [])
    )
    assert not any(ev.get("raw") == "L" for ev in events)

    # Confirm IN_TRAINING=true on the server persisted an empty-label capture
    empty_items = (
        httpx.get(f"{HIL_APP_URL}/ui/dataset/items?filter=empty", timeout=5.0)
        .json()
        .get("items", [])
    )
    assert len(empty_items) >= 1
    assert empty_items[0]["boxes"] == []


def test_serial_disconnect_fault_degrades_ui_and_recovers(page: Page):
    """Verify breaking virtual serial link disables UI controls and auto-recovers."""
    stub_external_cdns(page, HIL_APP_URL)
    try:
        httpx.post(
            f"{HIL_EMU_URL}/fault/disconnect",
            params={"enabled": "true"},
            timeout=3.0,
        ).raise_for_status()
        httpx.post(f"{HIL_EMU_URL}/reboot", timeout=5.0).raise_for_status()

        _wait_for_app_serial_connected(expected=False, timeout=15.0)

        page.goto(f"{HIL_APP_URL}/", wait_until="networkidle")
        expect(page.locator("#status-text")).to_have_text("Disabled (Open)")
        expect(page.locator("#btn-lock")).to_be_disabled()
        expect(page.locator("#btn-unlock")).to_be_disabled()
    finally:
        httpx.post(
            f"{HIL_EMU_URL}/fault/disconnect",
            params={"enabled": "false"},
            timeout=3.0,
        ).raise_for_status()
        httpx.post(f"{HIL_EMU_URL}/reboot", timeout=5.0).raise_for_status()

    _wait_for_app_serial_connected(expected=True, timeout=20.0)
    _wait_for_serial_line("READY:ULOCK:", timeout=10.0)
    page.reload(wait_until="networkidle")
    expect(page.locator("#status-text")).to_have_text("Unlocked")
    expect(page.locator("#btn-lock")).to_be_enabled()
