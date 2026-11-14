# pylint: disable=too-many-locals

"""Reolink camera snapshot receiver and ESP32 door lock controller.

Evaluates incoming camera motion webhooks, runs YOLO inference to detect
prey, commands the ESP32 to energize the lock ONLY during prey lockout,
and persists positive prey detection images and YOLO annotation labels
to /data/images and /data/labels for model fine-tuning and retraining.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from json.decoder import JSONDecodeError
from typing import Optional

# pylint: disable=import-error
import cv2
import httpx
import numpy as np
from fastapi import BackgroundTasks, FastAPI, Request
from ultralytics import YOLO
from ultralytics.engine.results import Results

import config
from esp32 import ESP32SerialController
from flasher import auto_flash_esp32_if_updated

# pylint: enable=import-error

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
        bin_path=getattr(
            config, "firmware_bin_path", "firmware_bin/firmware_sketch.ino.bin"
        ),
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


async def _trigger_dispenser(http_client: httpx.AsyncClient) -> None:
    """Send authenticated POST request to the oauth2-proxy protected /dispense API."""
    if not config.dispenser_url or not config.dispenser_password:
        logger.warning(
            "Dispenser skipped: DISPENSER_URL or DISPENSER_PASSWORD not set."
        )
        return

    payload = {
        "side": config.dispenser_side,
        "runsecs": config.dispenser_runsecs,
    }
    auth = httpx.BasicAuth(
        username=config.dispenser_user,
        password=config.dispenser_password,
    )

    try:
        resp = await http_client.post(
            config.dispenser_url,
            json=payload,
            auth=auth,
            timeout=10.0,
        )
        if resp.is_success:
            logger.info(
                "Dispenser triggered successfully (%d): %s",
                resp.status_code,
                resp.text,
            )
        else:
            logger.error(
                "Dispenser request rejected (%d): %s",
                resp.status_code,
                resp.text,
            )
    except httpx.RequestError as exc:
        logger.error("Network error calling dispenser API: %s", exc)


def _persist_training_pair(img: np.ndarray, result: Results) -> None:
    """Persist raw image and normalized YOLO bounding boxes."""
    try:
        base_name = f"prey_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
        img_path = os.path.join(config.images_dir, f"{base_name}.jpg")
        label_path = os.path.join(config.labels_dir, f"{base_name}.txt")

        # pylint: disable=no-member
        success = cv2.imwrite(img_path, img)
        # pylint: enable=no-member

        if not success:
            logger.error("Failed to write image snapshot to %s", img_path)
            return

        label_lines: list[str] = []
        if result.boxes is not None:
            # xywhn provides normalized (x_center, y_center, width, height) in range [0.0, 1.0]
            boxes_xywhn = result.boxes.xywhn.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy().astype(int)

            for cls_id, box in zip(classes, boxes_xywhn):
                x_c, y_c, width, height = box
                label_lines.append(
                    f"{cls_id} {x_c:.6f} {y_c:.6f} {width:.6f} {height:.6f}\n"
                )

        with open(label_path, "w", encoding="utf-8") as label_file:
            label_file.writelines(label_lines)

        logger.info("Persisted training pair: %s and %s", img_path, label_path)

    except OSError as exc:
        logger.error("Filesystem error while persisting training pair: %s", exc)


def _resolve_camera_url(client_host: Optional[str]) -> str:
    """Build camera base URL from webhook client IP, falling back to config.camera_url."""
    default_url = config.camera_url
    if not client_host or client_host == "unknown":
        return default_url
    host = f"[{client_host}]" if ":" in client_host else client_host
    return (
        f"https://{host}"  # assume HTTPS by default (configure via Reolink web admin)
    )


async def fetch_and_evaluate(
    state: AppState,
    background_tasks: BackgroundTasks,
    camera_base_url: str,
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
        # pylint: disable=no-member
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        # pylint: enable=no-member

        if img is None:
            logger.error("Failed to decode snapshot bytes into image array.")
            return

        t1 = time.perf_counter()
        results = state.model.predict(
            source=img, conf=config.conf_threshold, verbose=False
        )
        infer_ms = (time.perf_counter() - t1) * 1000

        if results and len(results[0].boxes) > 0:
            top_result = results[0]
            detected_classes = [
                state.model.names[int(cls_id)] for cls_id in top_result.boxes.cls
            ]
            confidences = [float(conf) for conf in top_result.boxes.conf]
            detections = list(zip(detected_classes, confidences))

            logger.info(
                "Detections: %s (Fetch: %.1fms, Infer: %.1fms)",
                detections,
                fetch_ms,
                infer_ms,
            )

            if any(name in config.target_classes for name in detected_classes):
                logger.warning(
                    ">>> PREY DETECTED! Activating lock for %ds...",
                    int(config.lockout_duration_sec),
                )
                state.controller.trigger_lock(config.lockout_duration_sec)
                background_tasks.add_task(_persist_training_pair, img, top_result)
            else:
                logger.info("Objects detected, but no prey criteria met.")
        else:
            logger.info(
                "No targets above %.0f%% confidence (Fetch: %.1fms, Infer: %.1fms).",
                config.conf_threshold * 100,
                fetch_ms,
                infer_ms,
            )

    except httpx.RequestError as exc:
        logger.error("Network error communicating with Reolink camera: %s", exc)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Unexpected error during evaluation pipeline: %s", exc, exc_info=True
        )


@app.post("/webhook/reolink")
async def reolink_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Handle incoming motion alert webhooks dispatched by the Reolink camera."""
    client_host = request.client.host if request.client else None
    client_port = request.client.port if request.client else "unknown"
    headers = dict(request.headers)
    camera_base_url = _resolve_camera_url(client_host)

    logger.info(
        "Webhook request from %s:%s -> target camera %s | Method: %s | URL: %s | Headers: %s",
        client_host or "unknown",
        client_port,
        camera_base_url,
        request.method,
        request.url,
        headers,
    )

    try:
        payload = await request.json()
        alarm_type = payload.get("alarm", {}).get("type", "Alarm Trigger")
        logger.info("Webhook event received: %s | Payload: %s", alarm_type, payload)
    except (JSONDecodeError, ValueError, UnicodeDecodeError):
        raw_body = await request.body()
        logger.info(
            "Webhook non-JSON body: %s", raw_body.decode("utf-8", errors="replace")
        )

    deps: AppState = request.app.state.deps
    background_tasks.add_task(
        fetch_and_evaluate, deps, background_tasks, camera_base_url
    )
    return {"status": "queued", "camera_url": camera_base_url}


@app.get("/health")
async def health(request: Request) -> dict:
    """Expose container health check metrics for Docker daemon and monitoring."""
    deps: AppState = request.app.state.deps
    controller = deps.controller
    model = deps.model

    now = time.time()
    is_serial_ok = bool(controller and controller.ser and controller.ser.is_open)
    is_model_loaded = model is not None
    is_lock_active = bool(controller and now < controller.lock_until)
    remaining_lockout = max(0.0, controller.lock_until - now) if controller else 0.0

    return {
        "status": "healthy",
        "serial_connected": is_serial_ok,
        "model_loaded": is_model_loaded,
        "lock_engaged": is_lock_active,
        "lockout_remaining_seconds": round(remaining_lockout, 1),
    }
