# pylint: disable=import-error,no-member
"""Unit tests for evaluator.py YOLO inference, locking, and training persistence."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import httpx
import numpy as np
import pytest

import config
import evaluator
import only_cats
from state import AppState
from tests.conftest import make_yolo_result


def _make_state(
    sample_jpeg_bytes: bytes | None = None,
    detections: list[tuple[int, float, list[float]]] | None = None,
    names: dict[int, str] | None = None,
) -> AppState:
    """Build an AppState with mocked controller, YOLO model, and HTTP client."""
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0

    mock_model = MagicMock()
    mock_model.names = names or {0: "prey", 1: "cat"}
    if detections is not None:
        mock_model.predict.return_value = [make_yolo_result(detections)]

    mock_http = AsyncMock()
    if sample_jpeg_bytes is not None:
        mock_http.get.return_value = MagicMock(
            status_code=200, content=sample_jpeg_bytes
        )

    return AppState(controller=mock_controller, model=mock_model, http_client=mock_http)


@pytest.mark.asyncio
async def test_fetch_and_evaluate_prey_detected_locks_persists_and_notifies(
    tmp_data_dirs, sample_jpeg_bytes
):
    """Positive prey detection must trigger lock, save .jpg/.txt, and send Signal alert."""
    images_dir, labels_dir = tmp_data_dirs
    state = _make_state(
        sample_jpeg_bytes=sample_jpeg_bytes,
        detections=[(0, 0.91, [0.5, 0.4, 0.2, 0.3])],
    )

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(
            state,
            config.camera_url,
            webhook_event={
                "alarm_type": "ANIMAL",
                "camera_url": config.camera_url,
            },
        )

    state.controller.trigger_lock.assert_called_once_with(config.lockout_duration_sec)
    saved_jpgs = list(images_dir.glob("prey_*.jpg"))
    saved_txts = list(labels_dir.glob("prey_*.txt"))
    assert len(saved_jpgs) == 1
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8").strip() == (
        "0 0.500000 0.400000 0.200000 0.300000"
    )

    mock_notify.assert_awaited_once()
    notify_kwargs = mock_notify.call_args[1]
    assert notify_kwargs["image_path"] == str(saved_jpgs[0])
    assert notify_kwargs["label_path"] == str(saved_txts[0])
    assert notify_kwargs["event_data"]["detections"] == [
        {"class": "prey", "confidence": 0.91}
    ]


@pytest.mark.asyncio
async def test_fetch_and_evaluate_test_event_with_zero_detections(
    tmp_data_dirs, sample_jpeg_bytes
):
    """TEST webhook event with 0 detections must lock, write empty .txt, and notify."""
    _, labels_dir = tmp_data_dirs
    state = _make_state(sample_jpeg_bytes=sample_jpeg_bytes, detections=[])

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(
            state,
            config.camera_url,
            webhook_event={"alarm_type": "TEST"},
        )

    state.controller.trigger_lock.assert_called_once()
    saved_txts = list(labels_dir.glob("prey_*.txt"))
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8") == ""
    mock_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_evaluate_non_prey_does_not_lock(
    tmp_data_dirs, sample_jpeg_bytes
):
    """Detections outside target_classes (e.g., 'cat') must not engage lock or persist."""
    images_dir, _ = tmp_data_dirs
    state = _make_state(
        sample_jpeg_bytes=sample_jpeg_bytes,
        detections=[(1, 0.88, [0.5, 0.5, 0.4, 0.4])],
    )

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(state, config.camera_url)

    state.controller.trigger_lock.assert_not_called()
    assert not list(images_dir.glob("*.jpg"))
    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_and_evaluate_in_training_persists_zero_detection_pair(
    tmp_data_dirs, sample_jpeg_bytes, monkeypatch
):
    """When in_training=True, 0 detections must persist train_*.jpg and empty .txt."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(config, "in_training", True)
    state = _make_state(sample_jpeg_bytes=sample_jpeg_bytes, detections=[])

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(state, config.camera_url)

    state.controller.trigger_lock.assert_not_called()
    mock_notify.assert_not_awaited()

    saved_jpgs = list(images_dir.glob("train_*.jpg"))
    saved_txts = list(labels_dir.glob("train_*.txt"))
    assert len(saved_jpgs) == 1
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_fetch_and_evaluate_in_training_persists_non_prey_detections(
    tmp_data_dirs, sample_jpeg_bytes, monkeypatch
):
    """When in_training=True, non-prey detections must persist train_*.jpg and boxes."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(config, "in_training", True)
    state = _make_state(
        sample_jpeg_bytes=sample_jpeg_bytes,
        detections=[(1, 0.88, [0.5, 0.5, 0.4, 0.4])],
    )

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(state, config.camera_url)

    state.controller.trigger_lock.assert_not_called()
    mock_notify.assert_not_awaited()

    saved_jpgs = list(images_dir.glob("train_*.jpg"))
    saved_txts = list(labels_dir.glob("train_*.txt"))
    assert len(saved_jpgs) == 1
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8").strip() == (
        "1 0.500000 0.500000 0.400000 0.400000"
    )


@pytest.mark.asyncio
async def test_fetch_and_evaluate_prey_during_admin_override_persists_and_notifies_without_locking(
    tmp_data_dirs, sample_jpeg_bytes
):
    """Prey detected during admin override must persist and notify while trigger_lock is a no-op."""
    images_dir, labels_dir = tmp_data_dirs
    state = _make_state(
        sample_jpeg_bytes=sample_jpeg_bytes,
        detections=[(0, 0.93, [0.5, 0.4, 0.2, 0.3])],
    )
    state.controller.admin_override = "unlocked"
    state.controller.trigger_lock.return_value = False

    with patch(
        "notifications.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await evaluator.fetch_and_evaluate(
            state,
            config.camera_url,
            webhook_event={"alarm_type": "ANIMAL"},
        )

    state.controller.trigger_lock.assert_called_once_with(config.lockout_duration_sec)
    assert len(list(images_dir.glob("prey_*.jpg"))) == 1
    assert len(list(labels_dir.glob("prey_*.txt"))) == 1
    mock_notify.assert_awaited_once()
    assert mock_notify.call_args[1]["event_data"]["lock_engaged"] is False
    assert mock_notify.call_args[1]["event_data"]["admin_override"] == "unlocked"


@pytest.mark.asyncio
async def test_fetch_and_evaluate_skips_on_uninitialized_state_or_camera_errors():
    """Verify early returns when state is incomplete, camera returns non-200, or HTTP fails."""
    # Uninitialized AppState
    await evaluator.fetch_and_evaluate(AppState(), config.camera_url)

    # Empty camera URL
    state = _make_state(sample_jpeg_bytes=b"")
    await evaluator.fetch_and_evaluate(state, "")
    state.http_client.get.assert_not_awaited()

    # Non-200 HTTP status from camera
    state.http_client.get.return_value = MagicMock(status_code=502, content=b"")
    await evaluator.fetch_and_evaluate(state, config.camera_url)
    state.model.predict.assert_not_called()

    # Network error from camera
    state.http_client.get.side_effect = httpx.ConnectError("camera unreachable")
    await evaluator.fetch_and_evaluate(state, config.camera_url)
    state.model.predict.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_and_evaluate_throttles_concurrent_bursts(sample_jpeg_bytes):
    """Verify at most 1 inference runs concurrently and excess webhook bursts drop."""
    state = _make_state(sample_jpeg_bytes=sample_jpeg_bytes, detections=[])

    active = 0
    max_active = 0

    def _slow_inference(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.08)
        active -= 1
        return MagicMock(), []

    with patch("evaluator.run_inference", side_effect=_slow_inference):
        await asyncio.gather(
            *(
                evaluator.fetch_and_evaluate(
                    state, config.camera_url, {"alarm_type": "ANIMAL"}
                )
                for _ in range(5)
            )
        )

    assert max_active == 1
    assert state.http_client.get.await_count <= 2


def _make_blurry_jpeg_bytes() -> bytes:
    """Encode a smooth, low-contrast frame with Laplacian variance well below 65.0."""
    frame = np.full((128, 128, 3), 120, dtype=np.uint8)
    # Soft Gaussian gradient with no sharp edges
    cv2.circle(frame, (64, 64), 30, (130, 130, 130), -1)
    frame = cv2.GaussianBlur(frame, (31, 31), 10.0)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()


@pytest.mark.asyncio
async def test_blurry_prey_frame_locks_door_without_persisting_dataset_pair(
    tmp_data_dirs, monkeypatch
):
    """Blurry frames must still trigger lock + Signal alert, but not save to images/ or labels/."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(config, "min_blur_variance", 65.0)
    monkeypatch.setattr(config, "signal_sender", "")
    monkeypatch.setattr(config, "signal_recipients", [])

    blurry_bytes = _make_blurry_jpeg_bytes()
    decoded_img = cv2.imdecode(
        np.frombuffer(blurry_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
    )

    model = MagicMock()
    model.names = {0: "prey"}
    yolo_result = make_yolo_result([(0, 0.91, [0.5, 0.5, 0.3, 0.3])])
    monkeypatch.setattr(
        evaluator, "run_inference", lambda *_args: (decoded_img, [yolo_result])
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = blurry_bytes

    http_client = AsyncMock()
    http_client.get.return_value = mock_resp

    controller = MagicMock()
    controller.trigger_lock.return_value = True
    controller.admin_override = None

    state = only_cats.AppState(
        controller=controller,
        model=model,
        http_client=http_client,
    )

    await evaluator.fetch_and_evaluate(
        state,
        camera_base_url="http://mock-camera:8080",
        webhook_event={"alarm_type": "ANIMAL"},
    )

    # Door lock must still engage on valid prey detection
    controller.trigger_lock.assert_called_once_with(config.lockout_duration_sec)
    # Neither image nor label/metadata files should be persisted
    assert not list(images_dir.iterdir())
    assert not list(labels_dir.iterdir())


@pytest.mark.asyncio
async def test_blurry_training_frame_is_not_persisted(tmp_data_dirs, monkeypatch):
    """When IN_TRAINING is enabled, blurry non-prey frames must also be skipped."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(config, "in_training", True)
    monkeypatch.setattr(config, "min_blur_variance", 65.0)

    blurry_bytes = _make_blurry_jpeg_bytes()
    decoded_img = cv2.imdecode(
        np.frombuffer(blurry_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
    )

    model = MagicMock()
    model.names = {0: "prey"}
    empty_result = make_yolo_result([])
    monkeypatch.setattr(
        evaluator, "run_inference", lambda *_args: (decoded_img, [empty_result])
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = blurry_bytes

    http_client = AsyncMock()
    http_client.get.return_value = mock_resp

    controller = MagicMock()
    state = only_cats.AppState(
        controller=controller,
        model=model,
        http_client=http_client,
    )

    await evaluator.fetch_and_evaluate(
        state,
        camera_base_url="http://mock-camera:8080",
        webhook_event={"alarm_type": "ANIMAL"},
    )

    controller.trigger_lock.assert_not_called()
    assert not list(images_dir.iterdir())
    assert not list(labels_dir.iterdir())


@pytest.mark.asyncio
async def test_benign_prelock_arms_cooldown_and_non_prelock_does_not(
    monkeypatch, sample_jpeg_bytes
):
    """Benign evaluation with prelock_engaged=True arms cooldown; prelock_engaged=False does not."""
    monkeypatch.setattr(config, "animal_prelock_cooldown_sec", 0.05)
    monkeypatch.setattr(config, "in_training", False)
    monkeypatch.setattr(
        evaluator,
        "run_inference",
        lambda *_a: (np.zeros((64, 64, 3)), [make_yolo_result([])]),
    )

    state = _make_state(sample_jpeg_bytes=sample_jpeg_bytes)

    # 1. prelock_engaged=False -> benign evaluation does not arm cooldown
    await evaluator.fetch_and_evaluate(
        state,
        "http://192.168.10.108",
        webhook_event={"alarm_type": "ANIMAL"},
        prelock_engaged=False,
    )
    state.controller.trigger_lock.assert_not_called()
    assert state.prelock_cooldown_until == 0.0

    # 2. prelock_engaged=True -> benign evaluation arms 0.05s cooldown
    await evaluator.fetch_and_evaluate(
        state,
        "http://192.168.10.108",
        webhook_event={"alarm_type": "ANIMAL"},
        prelock_engaged=True,
    )
    state.controller.trigger_lock.assert_not_called()
    assert state.prelock_cooldown_until > time.monotonic()

    # 3. Cooldown expires cleanly after 0.06s
    await asyncio.sleep(0.06)
    assert time.monotonic() >= state.prelock_cooldown_until


@pytest.mark.asyncio
@pytest.mark.usefixtures("tmp_data_dirs")
async def test_prey_detection_locks_immediately_even_during_prelock_cooldown(
    monkeypatch, sample_jpeg_bytes
):
    """Confirmed prey triggers full lockout and clears cooldown even while cooldown is active."""
    monkeypatch.setattr(config, "animal_prelock_duration_sec", 0.1)
    monkeypatch.setattr(config, "animal_prelock_cooldown_sec", 1.0)
    monkeypatch.setattr(config, "lockout_duration_sec", 5.0)
    monkeypatch.setattr(
        evaluator,
        "run_inference",
        lambda *_a: (
            np.zeros((64, 64, 3)),
            [make_yolo_result([(0, 0.92, [0.5, 0.5, 0.2, 0.2])])],
        ),
    )

    state = _make_state(sample_jpeg_bytes=sample_jpeg_bytes)
    state.prelock_cooldown_until = time.monotonic() + 1.0

    await evaluator.fetch_and_evaluate(
        state,
        "http://192.168.10.108",
        webhook_event={"alarm_type": "ANIMAL"},
        prelock_engaged=False,
    )

    state.controller.trigger_lock.assert_called_once_with(5.0)
    assert state.prelock_cooldown_until == 0.0
