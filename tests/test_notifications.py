# pylint: disable=import-error
"""Unit tests for notifications.py Signal alert delivery."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import notifications


@pytest.mark.asyncio
async def test_send_signal_prey_alert_includes_json_labels_and_attachments(
    tmp_path,
):
    """Verify non-empty label file and JPEG are attached and formatted in message."""
    img_file = tmp_path / "prey_1.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    lbl_file = tmp_path / "prey_1.txt"
    lbl_file.write_text("0 0.500000 0.500000 0.250000 0.250000\n", encoding="utf-8")

    mock_resp = MagicMock(is_success=True, status_code=201, text="ok")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client

    with patch("notifications.httpx.AsyncClient", return_value=mock_client):
        await notifications.send_signal_prey_alert(
            event_data={"alarm_type": "MD", "lockout_duration_sec": 300},
            image_path=img_file,
            label_path=lbl_file,
        )

    mock_client.post.assert_awaited_once()
    url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert url == f"{notifications.config.signal_api_url}/v2/send"

    payload = kwargs["json"]
    assert payload["number"] == notifications.config.signal_sender
    assert payload["recipients"] == notifications.config.signal_recipients
    assert '"alarm_type": "MD"' in payload["message"]
    assert "0 0.500000 0.500000 0.250000 0.250000" in payload["message"]
    assert len(payload["base64_attachments"]) == 2
    assert payload["base64_attachments"][0].startswith(
        "data:text/plain;filename=prey_1.txt;base64,"
    )
    assert payload["base64_attachments"][1].startswith(
        "data:image/jpeg;filename=prey_1.jpg;base64,"
    )


@pytest.mark.asyncio
async def test_send_signal_skips_empty_label_file(tmp_path):
    """Verify 0-byte label files (from TEST events) are omitted to prevent 400 errors."""
    img_file = tmp_path / "test_1.jpg"
    img_file.write_bytes(b"jpegdata")
    empty_lbl = tmp_path / "test_1.txt"
    empty_lbl.write_text("", encoding="utf-8")

    mock_resp = MagicMock(is_success=True, status_code=201, text="ok")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client

    with patch("notifications.httpx.AsyncClient", return_value=mock_client):
        await notifications.send_signal_prey_alert(
            event_data={"alarm_type": "TEST"},
            image_path=img_file,
            label_path=empty_lbl,
        )

    attachments = mock_client.post.call_args[1]["json"]["base64_attachments"]
    assert len(attachments) == 1
    expected_b64 = base64.b64encode(b"jpegdata").decode("ascii")
    assert (
        attachments[0] == f"data:image/jpeg;filename=test_1.jpg;base64,{expected_b64}"
    )
