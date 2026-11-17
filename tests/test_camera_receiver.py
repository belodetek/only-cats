# pylint: disable=import-error
"""Unit tests for camera_receiver.py webhook, inference, and persistence pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import camera_receiver
from tests.conftest import make_yolo_result


@pytest.mark.asyncio
async def test_fetch_and_evaluate_prey_detected_locks_persists_and_notifies(
    tmp_data_dirs, sample_jpeg_bytes, monkeypatch
):
    """Positive prey detection must trigger lock, save .jpg/.txt, and send Signal alert."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(camera_receiver.config, "target_classes", {"prey"})
    monkeypatch.setattr(camera_receiver.config, "lockout_duration_sec", 300.0)

    mock_model = MagicMock()
    mock_model.names = {0: "prey", 1: "cat"}
    mock_model.predict.return_value = [
        make_yolo_result([(0, 0.91, [0.5, 0.4, 0.2, 0.3])])
    ]

    mock_http = AsyncMock()
    mock_http.get.return_value = MagicMock(status_code=200, content=sample_jpeg_bytes)
    mock_controller = MagicMock()

    state = camera_receiver.AppState(
        controller=mock_controller, model=mock_model, http_client=mock_http
    )

    with patch(
        "camera_receiver.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await camera_receiver.fetch_and_evaluate(
            state,
            "https://192.168.10.108",
            webhook_event={"alarm_type": "MD", "camera_url": "https://192.168.10.108"},
        )

    mock_controller.trigger_lock.assert_called_once_with(300.0)
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
    mock_model = MagicMock()
    mock_model.names = {0: "prey"}
    mock_model.predict.return_value = [make_yolo_result([])]

    mock_http = AsyncMock()
    mock_http.get.return_value = MagicMock(status_code=200, content=sample_jpeg_bytes)
    mock_controller = MagicMock()

    state = camera_receiver.AppState(
        controller=mock_controller, model=mock_model, http_client=mock_http
    )

    with patch(
        "camera_receiver.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await camera_receiver.fetch_and_evaluate(
            state,
            "https://192.168.10.108",
            webhook_event={"alarm_type": "TEST"},
        )

    mock_controller.trigger_lock.assert_called_once()
    saved_txts = list(labels_dir.glob("prey_*.txt"))
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8") == ""
    mock_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_evaluate_non_prey_does_not_lock(
    tmp_data_dirs, sample_jpeg_bytes, monkeypatch
):
    """Detections outside target_classes (e.g., 'cat') must not engage lock."""
    images_dir, _ = tmp_data_dirs
    monkeypatch.setattr(camera_receiver.config, "target_classes", {"prey"})

    mock_model = MagicMock()
    mock_model.names = {0: "prey", 1: "cat"}
    mock_model.predict.return_value = [
        make_yolo_result([(1, 0.88, [0.5, 0.5, 0.4, 0.4])])
    ]

    mock_http = AsyncMock()
    mock_http.get.return_value = MagicMock(status_code=200, content=sample_jpeg_bytes)
    mock_controller = MagicMock()

    state = camera_receiver.AppState(
        controller=mock_controller, model=mock_model, http_client=mock_http
    )

    with patch(
        "camera_receiver.send_signal_prey_alert", new_callable=AsyncMock
    ) as mock_notify:
        await camera_receiver.fetch_and_evaluate(state, "https://192.168.10.108")

    mock_controller.trigger_lock.assert_not_called()
    assert not list(images_dir.glob("*.jpg"))
    mock_notify.assert_not_awaited()


def test_webhook_and_health_endpoints():
    """Verify FastAPI /webhook/reolink and /health routes with mocked AppState."""
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0

    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )

    with patch(
        "camera_receiver.fetch_and_evaluate", new_callable=AsyncMock
    ) as mock_eval:
        client = TestClient(camera_receiver.app, raise_server_exceptions=True)

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["serial_connected"] is True

        hook_resp = client.post("/webhook/reolink", json={"alarm": {"type": "TEST"}})
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        mock_eval.assert_awaited_once()
