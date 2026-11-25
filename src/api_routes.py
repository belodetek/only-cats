"""HTTP API routes for Reolink webhooks, manual lock overrides, and health checks."""

import logging
import time
from json.decoder import JSONDecodeError
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# pylint: disable=import-error
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)

# pylint: enable=import-error
import config
from evaluator import fetch_and_evaluate
from metrics import METRICS
from state import AppState
from utils import resolve_camera_url, verify_secret
from vision import format_model_date, load_model_metadata

_SENSITIVE_QUERY_KEYS = {"secret", "token", "api_key", "apikey", "password"}
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-webhook-secret",
    "x-api-key",
    "x-auth-request-access-token",
    "proxy-authorization",
}


logger = logging.getLogger(config.app_name)

router = APIRouter()


def _redact_url(raw_url: str) -> str:
    """Mask sensitive query parameter values in a URL string before logging."""
    parts = urlsplit(raw_url)
    if not parts.query:
        return raw_url
    redacted_query = urlencode(
        [
            (k, "[REDACTED]" if k.lower() in _SENSITIVE_QUERY_KEYS else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment)
    )


def _redact_headers(headers) -> dict[str, str]:
    """Return a copy of request headers with credential headers masked."""
    return {
        k: ("[REDACTED]" if k.lower() in _SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def _maybe_prelock_animal(deps: AppState, alarm_type: str) -> bool:
    """Engage short pre-lock on ANIMAL webhooks unless disabled or in cooldown."""
    if (
        not config.enable_animal_prelock
        or alarm_type != "ANIMAL"
        or not deps.controller
        or config.animal_prelock_duration_sec <= 0
    ):
        return False

    now = time.monotonic()
    cooldown_until = float(getattr(deps, "prelock_cooldown_until", 0.0))
    if now < cooldown_until:
        logger.info(
            "ANIMAL pre-lock suppressed by cooldown (%.1fs remaining); evaluating frame.",
            cooldown_until - now,
        )
        return False

    if deps.controller.trigger_lock(
        config.animal_prelock_duration_sec, dispense_on_expire=False
    ):
        logger.info(
            "Pre-locked door for %.1fs pending evaluation.",
            config.animal_prelock_duration_sec,
        )
        return True
    return False


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics on standard /metrics path."""
    payload, content_type = METRICS.render_prometheus()
    return Response(content=payload, media_type=content_type)


@router.post("/webhook/reolink")
async def reolink_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    secret: Optional[str] = Query(
        None, description="Webhook shared secret via query param"
    ),
    x_webhook_secret: Optional[str] = Header(
        None, alias="X-Webhook-Secret", description="Webhook shared secret via header"
    ),
) -> dict:
    """Handle incoming motion alert webhooks dispatched by the Reolink camera."""
    verify_secret(secret, x_webhook_secret)
    METRICS.webhooks_total.labels(outcome="received").inc()

    client_host = request.client.host if request.client else None
    client_port = request.client.port if request.client else "unknown"
    camera_base_url = resolve_camera_url(client_host)

    logger.info(
        "Webhook request from %s:%s -> target camera %s | Method: %s | URL: %s | Headers: %s",
        client_host or "unknown",
        client_port,
        camera_base_url,
        request.method,
        _redact_url(str(request.url)),
        _redact_headers(request.headers),
    )

    webhook_event: dict[str, Any] = {"camera_url": camera_base_url}
    alarm_type = ""
    try:
        payload = await request.json()
        alarm_type = str(payload.get("alarm", {}).get("type", "")).strip().upper()
        webhook_event["alarm_type"] = alarm_type
        webhook_event["webhook_payload"] = payload
        logger.info("Webhook event received: %s | Payload: %s", alarm_type, payload)
    except (JSONDecodeError, ValueError, UnicodeDecodeError):
        raw_body = await request.body()
        raw_text = raw_body.decode("utf-8", errors="replace")
        webhook_event["raw_body"] = raw_text
        logger.info("Webhook non-JSON body: %s", raw_text)

    if alarm_type not in config.allowed_alarm_types:
        logger.info(
            "Ignoring webhook alarm type '%s' (allowed: %s).",
            alarm_type or "UNKNOWN",
            sorted(config.allowed_alarm_types),
        )
        METRICS.webhooks_total.labels(outcome="ignored").inc()
        return {
            "status": "ignored",
            "alarm_type": alarm_type or None,
            "camera_url": camera_base_url,
        }

    deps: AppState = request.app.state.deps
    prelock_engaged = _maybe_prelock_animal(deps, alarm_type)

    background_tasks.add_task(
        fetch_and_evaluate,
        deps,
        camera_base_url,
        webhook_event,
        prelock_engaged=prelock_engaged,
    )
    METRICS.webhooks_total.labels(outcome="queued").inc()
    return {"status": "queued", "camera_url": camera_base_url}


@router.post("/lock")
async def force_lock(
    request: Request,
    secret: Optional[str] = Query(None, description="Shared secret via query param"),
    x_webhook_secret: Optional[str] = Header(
        None, alias="X-Webhook-Secret", description="Shared secret via header"
    ),
) -> dict:
    """Force the door lock closed persistently until /unlock or power loss."""
    verify_secret(secret, x_webhook_secret)
    deps: "AppState" = request.app.state.deps
    if not deps.controller:
        raise HTTPException(status_code=503, detail="Lock controller not initialized")
    deps.controller.admin_lock()
    return {"status": "locked", "admin_override": "locked"}


@router.post("/unlock")
async def force_unlock(
    request: Request,
    secret: Optional[str] = Query(None, description="Shared secret via query param"),
    x_webhook_secret: Optional[str] = Header(
        None, alias="X-Webhook-Secret", description="Shared secret via header"
    ),
) -> dict:
    """Force the door lock open persistently until /lock or power loss."""
    verify_secret(secret, x_webhook_secret)
    deps: "AppState" = request.app.state.deps
    if not deps.controller:
        raise HTTPException(status_code=503, detail="Lock controller not initialized")
    deps.controller.admin_unlock()
    return {"status": "unlocked", "admin_override": "unlocked"}


@router.get("/health")
async def health(request: Request) -> dict:
    """Expose container health check metrics for Docker daemon and monitoring."""
    deps: "AppState" = request.app.state.deps
    controller = deps.controller
    model = deps.model

    now = time.time()
    is_serial_ok = bool(controller and controller.is_connected)
    is_model_loaded = model is not None
    admin_override = controller.admin_override if controller else None
    is_lock_active = bool(
        controller
        and (
            admin_override == "locked"
            or (admin_override is None and now < controller.lock_until)
        )
    )
    remaining_lockout = (
        max(0.0, controller.lock_until - now)
        if controller and admin_override is None
        else 0.0
    )

    chip_desc = getattr(deps, "esp32_chip_desc", None)
    local_desc = getattr(deps, "esp32_local_desc", None)
    raw_model_meta = getattr(deps, "model_metadata", None) or load_model_metadata(
        config.model_weights_path
    )
    raw_model_date = raw_model_meta.get("date")
    raw_model_version = raw_model_meta.get("version")

    return {
        "status": "healthy",
        "serial_connected": is_serial_ok,
        "model_loaded": is_model_loaded,
        "model_metadata": {
            "version": (
                str(raw_model_version) if raw_model_version is not None else None
            ),
            "date": str(raw_model_date) if raw_model_date is not None else None,
            "short_date": format_model_date(raw_model_date),
            "task": raw_model_meta.get("task"),
            "imgsz": raw_model_meta.get("imgsz"),
            "description": raw_model_meta.get("description"),
        },
        "lock_engaged": is_lock_active,
        "admin_override": admin_override,
        "lockout_remaining_seconds": round(remaining_lockout, 1),
        "esp32_firmware": {
            "version": chip_desc.version if chip_desc else None,
            "built": f"{chip_desc.date} {chip_desc.time}" if chip_desc else None,
            "sha256": (
                chip_desc.app_elf_sha256[:4].hex()
                if chip_desc and chip_desc.app_elf_sha256
                else None
            ),
            "local_version": local_desc.version if local_desc else None,
        },
    }


@router.get("/model/metadata")
async def model_metadata(request: Request) -> dict:
    """Return parsed OpenVINO metadata.yaml for the active detection model."""
    deps: "AppState" = request.app.state.deps
    meta = getattr(deps, "model_metadata", None) or load_model_metadata(
        config.model_weights_path
    )
    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Model metadata not found for {config.model_weights_path}",
        )
    return {
        "weights_path": config.model_weights_path,
        "short_date": format_model_date(meta.get("date")),
        "metadata": meta,
    }
