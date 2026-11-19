# pylint: disable=too-many-locals

"""Reolink camera snapshot receiver and ESP32 door lock controller.

Evaluates incoming camera motion webhooks, runs YOLO inference to detect
prey, commands the ESP32 to energize the lock ONLY during prey lockout,
persists positive prey detection images and YOLO annotation labels
to /data/images and /data/labels for model fine-tuning and retraining,
and dispatches Signal alerts with event metadata, labels, and snapshot.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# pylint: disable=import-error
import httpx
import numpy as np
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

# pylint: enable=import-error
import config
import routes
import web_ui
from dispenser import trigger_dispenser as _trigger_dispenser
from esp32 import ESP32SerialController
from flasher import auto_flash_esp32_if_updated
from notifications import persist_and_notify
from vision import persist_training_pair, run_inference

logging.basicConfig(
    format="%(asctime)s - %(message)s", encoding="utf-8", level=config.level
)
logger = logging.getLogger(config.app_name)


# pylint: disable=too-few-public-methods
@dataclass
class AppState:
    """Encapsulates shared runtime dependencies without requiring global variables."""

    controller: Optional[ESP32SerialController] = None
    model: Optional[YOLO] = None
    http_client: Optional[httpx.AsyncClient] = None


# pylint: enable=too-few-public-methods


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Context manager handling service startup and shutdown events."""
    _uvicorn_formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
    for _uv_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _uv_logger = logging.getLogger(_uv_logger_name)
        for _handler in _uv_logger.handlers:
            _handler.setFormatter(_uvicorn_formatter)

    logger.info("Initializing NUC vision receiver...")

    state = AppState()

    os.makedirs(config.images_dir, exist_ok=True)
    os.makedirs(config.labels_dir, exist_ok=True)

    # Flash ESP32 over serial bootloader if binary has updated or chip is unprovisioned
    auto_flash_esp32_if_updated(
        port=config.serial_port,
        chip=getattr(config, "esp_chip", "esp32c6"),
        baud=getattr(config, "esp_flash_baud", 460800),
        bin_path=getattr(config, "firmware_bin_path", "flash/firmware_sketch.ino.bin"),
    )

    state.controller = ESP32SerialController(config.serial_port, config.baud_rate)
    state.controller.connect()
    state.controller.start_worker()

    if os.path.exists(config.model_weights_path):
        state.model = YOLO(config.model_weights_path)
        logger.info("Loaded custom weights from %s", config.model_weights_path)
    else:
        logger.error(
            "Weights file missing at %s! Check path.", config.model_weights_path
        )

    state.http_client = httpx.AsyncClient(timeout=4.0, verify=False)
    loop = asyncio.get_running_loop()
    state.controller.on_lockout_expired = lambda: asyncio.run_coroutine_threadsafe(
        _trigger_dispenser(state.http_client), loop
    )
    app_instance.state.deps = state

    yield

    if state.controller:
        state.controller.close()
    if state.http_client:
        await state.http_client.aclose()
    logger.info("Server shutdown finalized.")


app = FastAPI(title=config.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(web_ui.STATIC_DIR)), name="static")
app.include_router(routes.router)
app.include_router(web_ui.router)


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
        has_boxes = top_result is not None and len(top_result.boxes) > 0

        detected_classes = (
            [state.model.names[int(cls_id)] for cls_id in top_result.boxes.cls]
            if has_boxes
            else []
        )
        confidences = (
            [float(conf) for conf in top_result.boxes.conf] if has_boxes else []
        )
        detections = list(zip(detected_classes, confidences))

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
            lock_engaged = state.controller.trigger_lock(config.lockout_duration_sec)
            if lock_engaged:
                logger.warning(
                    ">>> %s! Activating lock for %ds...",
                    "TEST EVENT" if is_test else "PREY DETECTED",
                    int(config.lockout_duration_sec),
                )
            else:
                logger.warning(
                    ">>> %s! Lock trigger skipped (admin override: %s).",
                    "TEST EVENT" if is_test else "PREY DETECTED",
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
        elif config.in_training:
            logger.info("IN_TRAINING enabled: persisting training pair.")
            await asyncio.to_thread(persist_training_pair, img, top_result, "train")

    except httpx.RequestError as exc:
        logger.error("Network error communicating with Reolink camera: %s", exc)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Unexpected error during evaluation pipeline: %s", exc, exc_info=True
        )
