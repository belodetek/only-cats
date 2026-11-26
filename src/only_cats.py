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
from vision import load_model_metadata

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

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy", _CSP_POLICY.encode("latin-1")),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]


class _SecurityAndCsrfMiddleware:  # pylint: disable=too-few-public-methods
    """Pure ASGI middleware attaching security headers and enforcing CSRF on /ui/* mutations."""

    def __init__(self, app_asgi) -> None:
        self.app = app_asgi

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        if method in _STATE_CHANGING_METHODS and path.startswith("/ui/"):
            request = Request(scope, receive=receive)
            if request.headers.get("sec-fetch-site") == "cross-site":
                resp = web_ui.render_error_response(
                    request, 403, "Cross-site request blocked"
                )
                await resp(scope, receive, send)
                return

            origin = request.headers.get("origin")
            host = request.headers.get("x-forwarded-host") or request.headers.get(
                "host"
            )
            if origin and host and urlsplit(origin).netloc != host:
                resp = web_ui.render_error_response(request, 403, "Origin mismatch")
                await resp(scope, receive, send)
                return

            if request.headers.get("x-requested-with") not in {
                "XMLHttpRequest",
                "fetch",
            }:
                resp = web_ui.render_error_response(request, 403, "Missing CSRF header")
                await resp(scope, receive, send)
                return

        async def _send_with_headers(message):
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in raw_headers}
                for key, val in _SECURITY_HEADERS:
                    if key not in existing:
                        raw_headers.append((key, val))
                message = {**message, "headers": raw_headers}
            await send(message)

        await self.app(scope, receive, _send_with_headers)


class _SseSafeGZipMiddleware(GZipMiddleware):
    """Compress responses except Server-Sent Events streams which must flush immediately."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").endswith("/events"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


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
        state.model_metadata = load_model_metadata(config.model_weights_path)
        if state.model_metadata:
            logger.info(
                "Loaded custom weights from %s (date=%s, version=%s, task=%s, imgsz=%s)",
                config.model_weights_path,
                state.model_metadata.get("date", "unknown"),
                state.model_metadata.get("version", "unknown"),
                state.model_metadata.get("task", "unknown"),
                state.model_metadata.get("imgsz", "unknown"),
            )
        else:
            logger.info("Loaded custom weights from %s", config.model_weights_path)
    else:
        logger.error(
            "Weights file missing at %s! Check path.", config.model_weights_path
        )

    # Camera snapshots come from a self-signed LAN device, so this client skips
    # TLS verification. The dispenser sends BasicAuth credentials and can be a
    # remote host, so it gets a separate client with TLS verification enabled.
    state.http_client = httpx.AsyncClient(timeout=4.0, verify=False)
    state.dispenser_client = httpx.AsyncClient(timeout=10.0)
    loop = asyncio.get_running_loop()
    state.controller.on_lockout_expired = lambda: asyncio.run_coroutine_threadsafe(
        trigger_dispenser(state.dispenser_client), loop
    )
    app_instance.state.deps = state

    yield

    if state.controller:
        state.controller.close()
    if state.http_client:
        await state.http_client.aclose()
    if state.dispenser_client:
        await state.dispenser_client.aclose()
    logger.info("Server shutdown finalized.")


app = FastAPI(title=config.app_name, lifespan=lifespan)


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
app.add_middleware(_SecurityAndCsrfMiddleware)
app.add_middleware(_SseSafeGZipMiddleware, minimum_size=512)
