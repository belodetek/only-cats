# pylint: disable=broad-exception-caught
"""Signal notifications."""

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

# pylint: disable=import-error
import httpx
import numpy as np
from ultralytics.engine.results import Results

# pylint: enable=import-error
import config

logger = logging.getLogger("signal-notify")


def _encode_attachment(file_path: Path, mime_type: str) -> str | None:
    if not file_path.is_file() or file_path.stat().st_size == 0:
        return None
    raw = file_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};filename={file_path.name};base64,{b64}"


async def send_signal_prey_alert(
    event_data: dict[str, Any],
    image_path: str | Path | None = None,
    label_path: str | Path | None = None,
) -> None:
    """Send a Signal message containing pretty-printed event JSON, YOLO labels,
    and the JPEG frame.
    """
    if not (config.signal_sender and config.signal_recipients):
        logger.debug(
            "Signal notifications skipped: SIGNAL_SENDER or SIGNAL_RECIPIENTS not set."
        )
        return

    pretty_event = json.dumps(event_data, indent=2, default=str)

    label_text = ""
    attachments: list[str] = []

    if label_path:
        lbl_file = Path(label_path)
        if lbl_file.is_file():
            label_text = lbl_file.read_text(encoding="utf-8").strip()
            encoded_lbl = _encode_attachment(lbl_file, "text/plain")
            if encoded_lbl:
                attachments.append(encoded_lbl)

    if image_path:
        img_file = Path(image_path)
        encoded_img = _encode_attachment(img_file, "image/jpeg")
        if encoded_img:
            attachments.append(encoded_img)

    body_parts = [
        "🚨 Contraband - cat-flap locked",
        "",
        "Event:",
        pretty_event,
    ]
    if label_text:
        body_parts.extend(["", "Labels:", label_text])

    payload = {
        "message": "\n".join(body_parts),
        "number": config.signal_sender,
        "recipients": config.signal_recipients,
        "base64_attachments": attachments,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{config.signal_api_url}/v2/send", json=payload)
            if not resp.is_success:
                logger.error(
                    "Signal API rejected /v2/send (%d): %s",
                    resp.status_code,
                    resp.text,
                )
                return
            logger.info("Sent Signal prey alert to %s", config.signal_recipients)

    except Exception as exc:
        logger.error("Failed to send Signal prey alert: %s", exc)


async def persist_and_notify(
    img: np.ndarray,
    result: Optional[Results],
    event_data: dict[str, Any],
    persist_fn: Callable[[np.ndarray, Optional[Results]], Optional[tuple[str, str]]],
) -> None:
    """Save training pair to disk first, then send Signal prey alert with attachments."""
    saved = await asyncio.to_thread(persist_fn, img, result)
    img_path, label_path = saved if saved else (None, None)
    await send_signal_prey_alert(
        event_data=event_data,
        image_path=img_path,
        label_path=label_path,
    )
