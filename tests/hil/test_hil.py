# pylint: disable=too-many-arguments
"""Hardware-in-the-Loop (HiL) tests."""

import struct
import time
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import httpx
import pytest
from playwright.sync_api import Page, expect

# pylint: enable=import-error
import config
from flasher import ESP_APP_DESC_MAGIC
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


@pytest.fixture(scope="session", autouse=True)
def _verify_hil_services_ready() -> None:
    """Confirm all dependent services are ready and warm up OpenVINO inference."""
    last_status: dict[str, Any] = {}

    def _services_ready() -> bool:
        for name, url in (
            ("app", f"{HIL_APP_URL}/health"),
            ("emu", f"{HIL_EMU_URL}/health"),
            ("cam", f"{config.camera_url}/health"),
        ):
            try:
                resp = httpx.get(url, timeout=5.0)
                last_status[name] = (
                    resp.json() if resp.status_code == 200 else resp.status_code
                )
            except httpx.RequestError as exc:
                last_status[name] = repr(exc)

        return (
            isinstance(last_status.get("app"), dict)
            and last_status["app"].get("serial_connected") is True
            and isinstance(last_status.get("emu"), dict)
            and isinstance(last_status.get("cam"), dict)
        )

    try:
        _poll_with_backoff(
            _services_ready,
            timeout=90.0,
            initial_delay=0.25,
            max_delay=1.5,
            description="HiL services ready",
        )
    except AssertionError as exc:
        raise RuntimeError(f"Timed out waiting for services: {last_status}") from exc

    # Wait until QEMU ESP32-C6 firmware finishes cold-booting and prints READY:ULOCK:
    _wait_for_serial_line("READY:ULOCK:", timeout=60.0)

    # Warm up OpenVINO CPU graph compilation on empty.jpg (engages short ANIMAL pre-lock)
    httpx.post(f"{config.camera_url}/stage/empty.jpg", timeout=5.0).raise_for_status()
    trigger_camera_webhook("ANIMAL")
    _poll_with_backoff(
        lambda: (
            httpx.get(f"{HIL_APP_URL}/ui/dataset/items?filter=empty", timeout=5.0)
            .json()
            .get("items", [])
        ),
        timeout=20.0,
        initial_delay=0.25,
        max_delay=1.0,
        description="OpenVINO warm-up inference completion",
    )
    httpx.post(f"{HIL_EMU_URL}/serial/clear", timeout=5.0).raise_for_status()


@pytest.fixture(autouse=True)
def _reset_hil_state_between_tests():
    """Clear serial history before each HiL test."""
    httpx.post(f"{HIL_EMU_URL}/serial/clear", timeout=3.0).raise_for_status()
    yield


def _wait_for_unlock_complete(timeout: float) -> None:
    """Wait until the ESP32-C6 unlocks (if it ever ACKed a lock) and /health agrees."""
    last_events: list[dict[str, Any]] = []

    def _unlocked_on_serial() -> bool:
        nonlocal last_events
        resp = httpx.get(f"{HIL_EMU_URL}/serial/history", timeout=5.0)
        resp.raise_for_status()
        last_events = resp.json().get("events", [])
        ack_indices = [
            i for i, ev in enumerate(last_events) if "ACK:L" in ev.get("line", "")
        ]
        if not ack_indices:
            return True
        tail = last_events[ack_indices[-1] + 1 :]
        return any(
            "EVENT:TIMEOUT_UNLOCK" in ev.get("line", "")
            or "READY:ULOCK:" in ev.get("line", "")
            for ev in tail
        )

    try:
        _poll_with_backoff(
            _unlocked_on_serial,
            timeout=timeout,
            initial_delay=0.2,
            max_delay=1.0,
            description="ESP32 unlock (EVENT:TIMEOUT_UNLOCK or READY:ULOCK:)",
        )
    except AssertionError as exc:
        raise AssertionError(f"{exc}. Recent events: {last_events[-10:]}") from exc

    def _health_unlocked() -> bool:
        resp = httpx.get(f"{HIL_APP_URL}/health", timeout=5.0)
        return resp.status_code == 200 and resp.json().get("lock_engaged") is False

    _poll_with_backoff(
        _health_unlocked,
        timeout=10.0,
        initial_delay=0.15,
        max_delay=0.8,
        description="/health lock_engaged=False",
    )


def _read_local_firmware_version(bin_path: Path) -> str:
    """Extract the version string from the esp_app_desc_t header of a compiled .bin."""
    header = bin_path.read_bytes()[:0x50]
    assert len(header) >= 0x50, f"Firmware binary too small: {bin_path}"
    (magic,) = struct.unpack_from("<I", header, 0x20)
    assert (
        magic == ESP_APP_DESC_MAGIC
    ), f"Invalid esp_app_desc_t magic {hex(magic)} in {bin_path}"
    return header[0x30:0x50].split(b"\x00", 1)[0].decode("utf-8")


def _poll_with_backoff(
    fn,
    *,
    timeout: float = 20.0,
    initial_delay: float = 0.1,
    max_delay: float = 1.0,
    factor: float = 1.6,
    description: str = "condition",
):
    """Poll fn() until it returns a truthy result, backing off exponentially."""
    deadline = time.monotonic() + timeout
    delay = initial_delay
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
            last_exc = None
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            last_exc = exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(delay, remaining))
        delay = min(delay * factor, max_delay)
    raise AssertionError(
        f"Timed out after {timeout:.1f}s waiting for {description}"
        + (f" (last error: {last_exc!r})" if last_exc else "")
    )


def _wait_for_serial_line(substring: str, timeout: float = 20.0) -> dict[str, Any]:
    """Poll the QEMU PTY tee proxy with exponential backoff until a serial event matches."""
    last_events: list[dict[str, Any]] = []

    def _check() -> dict[str, Any] | None:
        nonlocal last_events
        resp = httpx.get(f"{HIL_EMU_URL}/serial/history", timeout=5.0)
        resp.raise_for_status()
        last_events = resp.json().get("events", [])
        for ev in last_events:
            if substring in ev.get("line", "") or substring in ev.get("raw", ""):
                return ev
        return None

    try:
        return _poll_with_backoff(
            _check,
            timeout=timeout,
            initial_delay=0.1,
            max_delay=1.0,
            description=f"serial event {substring!r}",
        )
    except AssertionError as exc:
        raise AssertionError(f"{exc}. Recent events: {last_events[-10:]}") from exc


def _wait_for_app_serial_connected(
    expected: bool = True, timeout: float = 30.0
) -> dict[str, Any]:
    """Poll /health with exponential backoff until serial_connected matches expected state."""
    last_health: dict[str, Any] = {}

    def _check() -> dict[str, Any] | None:
        nonlocal last_health
        resp = httpx.get(f"{HIL_APP_URL}/health", timeout=5.0)
        if resp.status_code == 200:
            last_health = resp.json()
            if bool(last_health.get("serial_connected")) is expected:
                return last_health
        return None

    try:
        return _poll_with_backoff(
            _check,
            timeout=timeout,
            initial_delay=0.15,
            max_delay=1.2,
            description=f"serial_connected={expected}",
        )
    except AssertionError as exc:
        raise AssertionError(f"{exc}. Last /health: {last_health}") from exc


def _reboot_and_wait_handshake(
    expected_prefix: str = "READY:ULOCK:",
    attempts: int = 2,
    per_attempt_timeout: float = 60.0,
) -> None:
    """Reboot QEMU and wait for READY:ULOCK handshake with a CI-safe boot timeout."""
    last_err: AssertionError | None = None
    for attempt in range(1, attempts + 1):
        httpx.post(f"{HIL_EMU_URL}/serial/clear", timeout=5.0).raise_for_status()
        httpx.post(f"{HIL_EMU_URL}/reboot", timeout=10.0).raise_for_status()
        try:
            _wait_for_serial_line(expected_prefix, timeout=per_attempt_timeout)
            _wait_for_app_serial_connected(expected=True, timeout=30.0)
            return
        except AssertionError as exc:
            last_err = exc
            if attempt < attempts:
                time.sleep(1.0)
    assert last_err is not None
    raise last_err


def test_real_firmware_handshake_and_health_endpoint():
    """Verify only-cats flashes/connects to QEMU ESP32-C6 and reports matching fw_version."""
    expected_version = _read_local_firmware_version(Path(config.firmware_bin_path))
    health = _wait_for_app_serial_connected(expected=True, timeout=60.0)
    assert health["model_loaded"] is True

    # Verify running firmware descriptor reported by /health matches compiled binary
    fw_info = health.get("esp32_firmware") or {}
    if fw_info.get("local_version"):
        assert fw_info["local_version"] == expected_version

    _reboot_and_wait_handshake(
        expected_prefix=f"READY:ULOCK:{expected_version}",
        attempts=2,
        per_attempt_timeout=60.0,
    )


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
        # Ensure lockout expires (or device boots unlocked) so subsequent tests start unlocked
        _wait_for_unlock_complete(timeout=config.lockout_duration_sec + 15.0)

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
        items = _poll_with_backoff(
            lambda: (
                httpx.get(f"{HIL_APP_URL}/ui/dataset/items?filter=prey", timeout=5.0)
                .json()
                .get("items", [])
            ),
            timeout=10.0,
            initial_delay=0.15,
            max_delay=1.0,
            description="prey dataset persistence",
        )
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
        # Ensure lockout expires (or device boots unlocked) so subsequent tests start unlocked
        _wait_for_unlock_complete(timeout=config.lockout_duration_sec + 15.0)


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
            timeout=5.0,
        ).raise_for_status()

    _reboot_and_wait_handshake(
        expected_prefix="READY:ULOCK:",
        attempts=2,
        per_attempt_timeout=60.0,
    )
    page.reload(wait_until="networkidle")
    expect(page.locator("#status-text")).to_have_text("Unlocked")
    expect(page.locator("#btn-lock")).to_be_enabled()
