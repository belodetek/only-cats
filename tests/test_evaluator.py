# pylint: disable=import-error
"""Unit tests for evaluator.py YOLO inference, locking, and training persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import config
import evaluator
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
