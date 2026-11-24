# pylint: disable=too-few-public-methods
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
from pathlib import Path
from urllib.parse import urlsplit

# pylint: disable=import-error
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope
from ultralytics import YOLO

# pylint: enable=import-error
import api_routes
import config
import web_ui
from dispenser import trigger_dispenser
from esp32 import ESP32SerialController
from flasher import auto_flash_esp32_if_updated
from state import AppState

logging.basicConfig(
    format="%(asctime)s - %(message)s", encoding="utf-8", level=config.level
)
logger = logging.getLogger(config.app_name)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class VersionedStaticFiles(StaticFiles):
    """Serve /static assets with immutable Cache-Control when ?v= query param is present."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Set long-lived immutable caching for versioned /static assets (?v=...)."""
        response = await super().get_response(path, scope)
        query_bytes = scope.get("query_string", b"")
        if response.status_code == 200 and b"v=" in query_bytes:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


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


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Attach anti-clickjacking, CSP, and MIME-sniffing headers to all responses."""
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
    return response


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """Block cross-site state-changing Web UI requests via Origin and custom-header checks."""
    if request.method in _STATE_CHANGING_METHODS and request.url.path.startswith(
        "/ui/"
    ):
        if request.headers.get("sec-fetch-site") == "cross-site":
            return web_ui.render_error_response(
                request, 403, "Cross-site request blocked"
            )

        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin and host and urlsplit(origin).netloc != host:
            return web_ui.render_error_response(request, 403, "Origin mismatch")

        if request.headers.get("x-requested-with") not in {"XMLHttpRequest", "fetch"}:
            return web_ui.render_error_response(request, 403, "Missing CSRF header")

    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> HTMLResponse | JSONResponse:
    """Serve friendly HTML error pages to browsers while keeping JSON for APIs."""
    return web_ui.render_error_response(request, exc.status_code, str(exc.detail or ""))


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, _exc: Exception
) -> HTMLResponse | JSONResponse:
    """Catch unhandled server errors cleanly."""
    return web_ui.render_error_response(request, 500)


app.mount(
    "/static",
    VersionedStaticFiles(directory=str(STATIC_DIR)),
    name="static",
)
app.include_router(api_routes.router)
app.include_router(web_ui.router)
app.add_middleware(GZipMiddleware, minimum_size=512)
