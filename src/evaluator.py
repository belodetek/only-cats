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
import dataset
from metrics import METRICS
from notifications import persist_and_notify
from state import AppState
from vision import compute_sharpness, run_inference

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


def _yolo_boxes_from_result(top_result: Any) -> list[dataset.YoloBox]:
    """Convert Ultralytics YOLO result boxes into validated YoloBox models."""
    if top_result is None or top_result.boxes is None or len(top_result.boxes) == 0:
        return []

    boxes_xywhn = top_result.boxes.xywhn.cpu().numpy()
    classes = top_result.boxes.cls.cpu().numpy().astype(int)

    boxes: list[dataset.YoloBox] = []
    for cls_id, coords in zip(classes, boxes_xywhn):
        cx = round(float(coords[0]), 6)
        cy = round(float(coords[1]), 6)
        w = round(float(coords[2]), 6)
        h = round(float(coords[3]), 6)
        if 0.0 < w <= 1.0 and 0.0 < h <= 1.0:
            boxes.append(dataset.YoloBox(cls=int(cls_id), x=cx, y=cy, w=w, h=h))
    return boxes


def _persist_clean_pair(
    raw_bytes: bytes,
    top_result: Any,
    prefix: str = "prey",
    meta: Optional[dict[str, Any]] = None,
) -> Optional[tuple[str, str]]:
    """Persist metadata-stripped JPEG, YOLO .txt labels, and sidecar .json if sharp enough."""
    sharpness = compute_sharpness(raw_bytes)
    if meta is not None:
        meta["sharpness"] = round(sharpness, 1)

    if sharpness < config.min_blur_variance:
        logger.info(
            "Skipping dataset persistence for blurry %s frame (sharpness=%.1f < %.1f).",
            prefix,
            sharpness,
            config.min_blur_variance,
        )
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    stem = f"{prefix}_{stamp}" if prefix else stamp
    boxes = _yolo_boxes_from_result(top_result)
    img_path = dataset.save_clean_capture(
        stem=stem,
        raw_image_bytes=raw_bytes,
        boxes=boxes,
        meta=meta,
    )
    label_path = img_path.parent.parent / "labels" / f"{img_path.stem}.txt"
    return str(img_path), str(label_path)


async def _handle_prey_match(
    state: AppState,
    raw_bytes: bytes,
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

    raw_override = state.controller.admin_override
    admin_override = raw_override if isinstance(raw_override, str) else None

    event_data: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": "TEST" if is_test else "ANIMAL",
        "lockout_duration_sec": int(config.lockout_duration_sec),
        "lock_engaged": bool(lock_engaged),
        "admin_override": admin_override,
        "fetch_ms": round(fetch_ms, 1),
        "infer_ms": round(infer_ms, 1),
        "detections": [
            {"class": cls_name, "confidence": round(conf, 4)}
            for cls_name, conf in detections
        ],
        **(webhook_event or {}),
    }

    def _persist_with_meta(
        _img: np.ndarray, result: Any, prefix: str = "prey"
    ) -> Optional[tuple[str, str]]:
        return _persist_clean_pair(raw_bytes, result, prefix=prefix, meta=event_data)

    METRICS.record_prey_detection(detections, is_test=is_test)
    await persist_and_notify(img, top_result, event_data, _persist_with_meta)


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
        METRICS.camera_fetch_seconds.observe(fetch_ms / 1000.0)

        if resp.status_code != 200:
            logger.error("Camera returned non-200 HTTP status: %d", resp.status_code)
            return

        raw_bytes = resp.content
        img_array = np.frombuffer(raw_bytes, dtype=np.uint8)

        t1 = time.perf_counter()
        img, results = await asyncio.to_thread(
            run_inference, state.model, img_array, config.conf_threshold
        )
        infer_ms = (time.perf_counter() - t1) * 1000
        METRICS.yolo_infer_seconds.observe(infer_ms / 1000.0)

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
                raw_bytes,
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
            train_meta: dict[str, Any] = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event_type": "TRAINING",
                "fetch_ms": round(fetch_ms, 1),
                "infer_ms": round(infer_ms, 1),
                "detections": [
                    {"class": cls_name, "confidence": round(conf, 4)}
                    for cls_name, conf in detections
                ],
                **(webhook_event or {}),
            }
            await asyncio.to_thread(
                _persist_clean_pair, raw_bytes, top_result, "train", train_meta
            )

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
