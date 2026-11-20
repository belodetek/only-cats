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
from contextlib import asynccontextmanager

# pylint: disable=import-error
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

# pylint: enable=import-error
import config
import routes
import web_ui
from dispenser import trigger_dispenser
from esp32 import ESP32SerialController
from flasher import auto_flash_esp32_if_updated
from state import AppState

logging.basicConfig(
    format="%(asctime)s - %(message)s", encoding="utf-8", level=config.level
)
logger = logging.getLogger(config.app_name)


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
    _, chip_desc, local_desc = auto_flash_esp32_if_updated(
        port=config.serial_port,
        chip=config.esp_chip,
        baud=config.esp_flash_baud,
        bin_path=config.firmware_bin_path,
    )
    state.esp32_chip_desc = chip_desc
    state.esp32_local_desc = local_desc

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
        trigger_dispenser(state.http_client), loop
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
