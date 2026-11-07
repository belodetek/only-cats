# pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
"""Snapshot retrieval, YOLO prey evaluation, and lockout orchestration."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

# pylint: disable=import-error
import httpx
import numpy as np

# pylint: enable=import-error
import config
from notifications import persist_and_notify
from state import AppState
from vision import persist_training_pair, run_inference

logger = logging.getLogger(config.app_name)

_MAX_PENDING_EVALUATIONS = 1


def _extract_detections(
    model: Any, top_result: Any
) -> tuple[list[str], list[tuple[str, float]]]:
    """Extract class names and (class, confidence) pairs from the top YOLO result."""
    if top_result is None or len(top_result.boxes) == 0:
        return [], []
    detected_classes = [model.names[int(cls_id)] for cls_id in top_result.boxes.cls]
    confidences = [float(conf) for conf in top_result.boxes.conf]
    return detected_classes, list(zip(detected_classes, confidences))


async def _handle_prey_match(
    state: AppState,
    img: np.ndarray,
    top_result: Any,
    is_test: bool,
    fetch_ms: float,
    infer_ms: float,
    detections: list[tuple[str, float]],
    webhook_event: Optional[dict[str, Any]],
) -> None:
    """Trigger the door lock and dispatch persistence + Signal notification."""
    assert state.controller is not None
    lock_engaged = state.controller.trigger_lock(config.lockout_duration_sec)
    event_label = "TEST EVENT" if is_test else "PREY DETECTED"
    if lock_engaged:
        logger.warning(
            ">>> %s! Activating lock for %ds...",
            event_label,
            int(config.lockout_duration_sec),
        )
    else:
        logger.warning(
            ">>> %s! Lock trigger skipped (admin override: %s).",
            event_label,
            state.controller.admin_override,
        )

    event_data: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "lockout_duration_sec": int(config.lockout_duration_sec),
        "lock_engaged": bool(lock_engaged),
        "admin_override": state.controller.admin_override,
        "fetch_ms": round(fetch_ms, 1),
        "infer_ms": round(infer_ms, 1),
        "detections": [
            {"class": cls_name, "confidence": round(conf, 4)}
            for cls_name, conf in detections
        ],
        **(webhook_event or {}),
    }
    await persist_and_notify(img, top_result, event_data, persist_training_pair)


async def _run_evaluation_pipeline(
    state: AppState,
    camera_base_url: str,
    webhook_event: Optional[dict[str, Any]],
) -> None:
    """Execute snapshot fetch, YOLO inference, and lockout/notification handling."""
    snap_url = (
        f"{camera_base_url}/cgi-bin/api.cgi?"
        f"cmd=Snap&channel={config.camera_channel}&"
        f"user={config.camera_user}&"
        f"password={config.camera_password}"
    )

    try:
        t0 = time.perf_counter()
        resp = await state.http_client.get(snap_url)
        fetch_ms = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            logger.error("Camera returned non-200 HTTP status: %d", resp.status_code)
            return

        img_array = np.frombuffer(resp.content, dtype=np.uint8)

        t1 = time.perf_counter()
        img, results = await asyncio.to_thread(
            run_inference, state.model, img_array, config.conf_threshold
        )
        infer_ms = (time.perf_counter() - t1) * 1000

        if img is None:
            logger.error("Failed to decode snapshot bytes into image array.")
            return

        is_test = bool(
            webhook_event and str(webhook_event.get("alarm_type", "")).upper() == "TEST"
        )
        top_result = results[0] if results else None
        detected_classes, detections = _extract_detections(state.model, top_result)

        if detections:
            logger.info(
                "Detections: %s (Fetch: %.1fms, Infer: %.1fms)",
                detections,
                fetch_ms,
                infer_ms,
            )
        else:
            logger.info(
                "No targets above %.0f%% confidence (Fetch: %.1fms, Infer: %.1fms).",
                config.conf_threshold * 100,
                fetch_ms,
                infer_ms,
            )

        if is_test or any(name in config.target_classes for name in detected_classes):
            await _handle_prey_match(
                state,
                img,
                top_result,
                is_test,
                fetch_ms,
                infer_ms,
                detections,
                webhook_event,
            )
        elif config.in_training:
            logger.info("IN_TRAINING enabled: persisting training pair.")
            await asyncio.to_thread(persist_training_pair, img, top_result, "train")

    except httpx.RequestError as exc:
        logger.error("Network error communicating with Reolink camera: %s", exc)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Unexpected error during evaluation pipeline: %s", exc, exc_info=True
        )


async def fetch_and_evaluate(
    state: AppState,
    camera_base_url: str,
    webhook_event: Optional[dict[str, Any]] = None,
) -> None:
    """Retrieve snapshot from Reolink camera, run YOLO, and handle lock state."""
    if not state.model or not state.http_client or not state.controller:
        logger.error(
            "Evaluation skipped: application components not fully initialized."
        )
        return

    if not camera_base_url:
        logger.error("Evaluation skipped: camera URL could not be resolved.")
        return

    if state.eval_semaphore is None:
        state.eval_semaphore = asyncio.Semaphore(1)

    if (
        state.eval_semaphore.locked()
        and state.pending_evaluations >= _MAX_PENDING_EVALUATIONS
    ):
        logger.warning(
            "Dropping redundant webhook burst (%s): inference queue full.",
            (webhook_event or {}).get("alarm_type", "UNKNOWN"),
        )
        return

    state.pending_evaluations += 1
    try:
        async with state.eval_semaphore:
            state.pending_evaluations -= 1
            await _run_evaluation_pipeline(state, camera_base_url, webhook_event)
    except BaseException:
        if state.pending_evaluations > 0:
            state.pending_evaluations -= 1
        raise
