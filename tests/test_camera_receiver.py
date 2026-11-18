# pylint: disable=import-error,protected-access
"""Unit tests for camera_receiver.py webhook, inference, and persistence pipeline."""

import ipaddress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import camera_receiver
from tests.conftest import make_yolo_result


def test_resolve_camera_url_ipv4():
    """Verify _resolve_camera_url formats standard IPv4 address in camera_networks."""
    assert (
        camera_receiver._resolve_camera_url("192.168.10.108")
        == "https://192.168.10.108"
    )


def test_resolve_camera_url_allowed_ipv6(monkeypatch):
    """Verify _resolve_camera_url formats IPv6 in brackets
    when explicitly allowed in camera_networks.
    """
    monkeypatch.setattr(
        camera_receiver.config,
        "camera_networks",
        {ipaddress.ip_network("fd00::/8")},
    )
    assert camera_receiver._resolve_camera_url("fd00::1") == "https://[fd00::1]"


def test_resolve_camera_url_rejects_untrusted_and_public_ips():
    """Verify _resolve_camera_url rejects public IPs not in camera_networks with 403."""
    with pytest.raises(HTTPException) as exc_v6:
        camera_receiver._resolve_camera_url("2001:db8::1")
    assert exc_v6.value.status_code == 403
    assert exc_v6.value.detail == "Client IP not in trusted camera subnet"

    with pytest.raises(HTTPException) as exc_v4:
        camera_receiver._resolve_camera_url("8.8.8.8")
    assert exc_v4.value.status_code == 403
    assert exc_v4.value.detail == "Client IP not in trusted camera subnet"


def test_resolve_camera_url_rejects_invalid_ip():
    """Verify _resolve_camera_url raises 400 when client host is not a valid IP."""
    with pytest.raises(HTTPException) as exc_info:
        camera_receiver._resolve_camera_url("not-an-ip")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid client IP"


def test_resolve_camera_url_rejects_loopback_and_link_local():
    """Verify _resolve_camera_url raises 403 on loopback or link-local addresses."""
    with pytest.raises(HTTPException) as exc_loopback:
        camera_receiver._resolve_camera_url("127.0.0.1")
    assert exc_loopback.value.status_code == 403

    with pytest.raises(HTTPException) as exc_linklocal:
        camera_receiver._resolve_camera_url("169.254.1.1")
    assert exc_linklocal.value.status_code == 403


def test_resolve_camera_url_fallback_when_none_or_unknown(monkeypatch):
    """Verify _resolve_camera_url falls back to config.camera_url when client host is missing."""
    monkeypatch.setattr(
        camera_receiver.config, "camera_url", "https://default-camera:443"
    )
    assert camera_receiver._resolve_camera_url(None) == "https://default-camera:443"
    assert (
        camera_receiver._resolve_camera_url("unknown") == "https://default-camera:443"
    )
    assert camera_receiver._resolve_camera_url("") == "https://default-camera:443"


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
    """Detections outside target_classes (e.g., 'cat') must not engage lock
    or persist when not training."""
    images_dir, _ = tmp_data_dirs
    monkeypatch.setattr(camera_receiver.config, "target_classes", {"prey"})
    monkeypatch.setattr(camera_receiver.config, "in_training", False)

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


@pytest.mark.asyncio
async def test_fetch_and_evaluate_in_training_persists_zero_detection_pair(
    tmp_data_dirs, sample_jpeg_bytes, monkeypatch
):
    """When in_training=True, 0 detections must persist train_*.jpg
    and empty .txt without locking."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(camera_receiver.config, "in_training", True)

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
        await camera_receiver.fetch_and_evaluate(state, "https://192.168.10.108")

    mock_controller.trigger_lock.assert_not_called()
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
    """When in_training=True, non-prey detections must persist train_*.jpg and bounding boxes."""
    images_dir, labels_dir = tmp_data_dirs
    monkeypatch.setattr(camera_receiver.config, "target_classes", {"prey"})
    monkeypatch.setattr(camera_receiver.config, "in_training", True)

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
    mock_notify.assert_not_awaited()

    saved_jpgs = list(images_dir.glob("train_*.jpg"))
    saved_txts = list(labels_dir.glob("train_*.txt"))
    assert len(saved_jpgs) == 1
    assert len(saved_txts) == 1
    assert saved_txts[0].read_text(encoding="utf-8").strip() == (
        "1 0.500000 0.500000 0.400000 0.400000"
    )


def test_webhook_and_health_endpoints(monkeypatch):
    """Verify FastAPI /webhook/reolink and /health routes with mocked AppState."""
    monkeypatch.setattr(camera_receiver.config, "webhook_secret", "test-secret")
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0

    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )

    with patch(
        "camera_receiver.fetch_and_evaluate", new_callable=AsyncMock
    ) as mock_eval:
        client = TestClient(
            camera_receiver.app,
            client=("192.168.10.108", 50000),
            raise_server_exceptions=True,
        )

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["serial_connected"] is True

        hook_resp = client.post(
            "/webhook/reolink",
            params={"secret": "test-secret"},
            json={"alarm": {"type": "TEST"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        assert hook_resp.json()["camera_url"] == "https://192.168.10.108"

        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == "https://192.168.10.108"
        assert args[2]["camera_url"] == "https://192.168.10.108"
        assert args[2]["alarm_type"] == "TEST"


def test_webhook_accepts_x_webhook_secret_header(monkeypatch):
    """Verify webhook endpoint accepts shared secret via X-Webhook-Secret header."""
    monkeypatch.setattr(camera_receiver.config, "webhook_secret", "test-secret")
    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0

    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )

    with patch(
        "camera_receiver.fetch_and_evaluate", new_callable=AsyncMock
    ) as mock_eval:
        client = TestClient(
            camera_receiver.app,
            client=("192.168.10.108", 50000),
            raise_server_exceptions=True,
        )

        hook_resp = client.post(
            "/webhook/reolink",
            headers={"X-Webhook-Secret": "test-secret"},
            json={"alarm": {"type": "TEST"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        mock_eval.assert_awaited_once()


def test_webhook_rejects_missing_or_invalid_secret(monkeypatch):
    """Verify webhook endpoint returns 401 when secret is missing or invalid."""
    monkeypatch.setattr(camera_receiver.config, "webhook_secret", "test-secret")
    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=MagicMock(), model=MagicMock(), http_client=AsyncMock()
    )
    client = TestClient(
        camera_receiver.app,
        client=("192.168.10.108", 50000),
        raise_server_exceptions=False,
    )

    # Missing secret
    resp_missing = client.post("/webhook/reolink", json={"alarm": {"type": "TEST"}})
    assert resp_missing.status_code == 401
    assert resp_missing.json()["detail"] == "Invalid webhook secret"

    # Invalid query param secret
    resp_bad = client.post(
        "/webhook/reolink",
        params={"secret": "wrong-secret"},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp_bad.status_code == 401
    assert resp_bad.json()["detail"] == "Invalid webhook secret"

    # Invalid header secret
    resp_bad_hdr = client.post(
        "/webhook/reolink",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp_bad_hdr.status_code == 401
    assert resp_bad_hdr.json()["detail"] == "Invalid webhook secret"


def test_webhook_rejects_untrusted_client_ip(monkeypatch):
    """Verify webhook endpoint returns 403 when client IP is not in camera_networks."""
    monkeypatch.setattr(camera_receiver.config, "webhook_secret", "test-secret")
    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=MagicMock(), model=MagicMock(), http_client=AsyncMock()
    )
    client = TestClient(
        camera_receiver.app,
        client=("2001:db8::1", 50000),
        raise_server_exceptions=False,
    )
    resp = client.post(
        "/webhook/reolink",
        params={"secret": "test-secret"},
        json={"alarm": {"type": "TEST"}},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Client IP not in trusted camera subnet"


def test_webhook_resolves_default_camera_url_when_client_host_unknown(monkeypatch):
    """Verify webhook endpoint falls back to config.camera_url when client host is unknown."""
    monkeypatch.setattr(camera_receiver.config, "webhook_secret", "test-secret")
    monkeypatch.setattr(camera_receiver.config, "camera_url", "https://10.42.84.168")

    mock_controller = MagicMock()
    mock_controller.ser.is_open = True
    mock_controller.lock_until = 0.0

    camera_receiver.app.state.deps = camera_receiver.AppState(
        controller=mock_controller, model=MagicMock(), http_client=AsyncMock()
    )

    with patch(
        "camera_receiver.fetch_and_evaluate", new_callable=AsyncMock
    ) as mock_eval:
        client = TestClient(
            camera_receiver.app,
            client=("unknown", 0),
            raise_server_exceptions=True,
        )

        hook_resp = client.post(
            "/webhook/reolink",
            params={"secret": "test-secret"},
            json={"alarm": {"type": "MD"}},
        )
        assert hook_resp.status_code == 200
        assert hook_resp.json()["status"] == "queued"
        assert hook_resp.json()["camera_url"] == "https://10.42.84.168"

        mock_eval.assert_awaited_once()
        args, _ = mock_eval.call_args
        assert args[1] == "https://10.42.84.168"
        assert args[2]["camera_url"] == "https://10.42.84.168"
