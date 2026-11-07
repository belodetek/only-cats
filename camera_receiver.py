"""Reolink camera snapshot receiver and ESP32 USB lock controller.

Evaluates incoming camera motion webhooks, runs YOLO inference to detect
prey, and commands the ESP32 to energize the lock ONLY during prey lockout.
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from json.decoder import JSONDecodeError
from typing import Optional

# pylint: disable=import-error
import cv2
import httpx
import numpy as np
import serial
from fastapi import BackgroundTasks, FastAPI, Request
from ultralytics import YOLO

import config
from flasher import auto_flash_esp32_if_updated

# pylint: enable=import-error


logging.basicConfig(
    format="%(asctime)s - %(message)s", encoding="utf-8", level=config.level
)
logger = logging.getLogger(config.app_name)


class ESP32SerialController:
    """Manages the USB serial link to the ESP32 and runs the lock command loop."""

    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock_until = 0.0

    def connect(self) -> None:
        """Establish the serial connection to the ESP32 device."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
            time.sleep(2.0)  # Allow ESP32 auto-reset to settle
            logger.info("Connected to ESP32 on %s at %d baud", self.port, self.baudrate)
        except (serial.SerialException, OSError) as exc:
            logger.error("Failed to open serial port %s: %s", self.port, exc)
            self.ser = None

    def start_worker(self) -> None:
        """Spawn the background thread that feeds the active lock command."""
        if self.ser and self.ser.is_open:
            self.running = True
            self.thread = threading.Thread(target=self._command_loop, daemon=True)
            self.thread.start()
            logger.info("Serial command thread started.")

    def _command_loop(self) -> None:
        """Sends 'L' each second ONLY while actively in a prey lockout window."""
        while self.running:
            now = time.time()
            with self.lock:
                if self.ser and self.ser.is_open and now < self.lock_until:
                    try:
                        self.ser.write(b"L")
                        logger.debug("Lock keepalive sent: 'L'")
                    except serial.SerialException as exc:
                        logger.error("Serial write failed: %s", exc)
            time.sleep(config.command_interval_sec)

    def trigger_lock(self, duration: float = config.lockout_duration_sec) -> None:
        """Engage the lock and send 'L' for the specified duration."""
        with self.lock:
            new_target = time.time() + duration
            self.lock_until = max(self.lock_until, new_target)
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(b"L")
                except serial.SerialException:
                    pass
            logger.warning(
                ">>> PREY LOCKOUT ACTIVATED: Holding lock ON for %.1fs (until %s)",
                duration,
                time.strftime("%H:%M:%S", time.localtime(self.lock_until)),
            )

    def close(self) -> None:
        """Stop background worker and terminate serial connection."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except (serial.SerialException, OSError):
                    pass
        logger.info("ESP32 serial connection closed.")


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
    logger.info("Initializing NUC vision receiver...")
    state = AppState()

    # Flash ESP32 over serial bootloader if binary has updated or chip is unprovisioned
    auto_flash_esp32_if_updated(
        port=config.serial_port,
        chip=getattr(config, "esp_chip", "esp32c3"),
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
    app_instance.state.deps = state

    yield

    if state.controller:
        state.controller.close()
    if state.http_client:
        await state.http_client.aclose()
    logger.info("Server shutdown finalized.")


app = FastAPI(title=config.app_name, lifespan=lifespan)


async def fetch_and_evaluate(state: AppState) -> None:
    """Retrieve snapshot from Reolink camera, run YOLO, and handle lock state."""
    if not state.model or not state.http_client or not state.controller:
        logger.error(
            "Evaluation skipped: application components not fully initialized."
        )
        return

    snap_url = (
        f"{config.camera_url}/cgi-bin/api.cgi?"
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
            detected_classes = [
                state.model.names[int(cls_id)] for cls_id in results[0].boxes.cls
            ]
            confidences = [float(conf) for conf in results[0].boxes.conf]
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
    try:
        payload = await request.json()
        alarm_type = payload.get("alarm", {}).get("type", "Alarm Trigger")
        logger.info("Webhook event received: %s", alarm_type)
    except (JSONDecodeError, ValueError, UnicodeDecodeError):
        pass

    deps: AppState = request.app.state.deps
    background_tasks.add_task(fetch_and_evaluate, deps)
    return {"status": "queued"}


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
