"""HTTP API routes for Reolink webhooks, manual lock overrides, and health checks."""

import logging
import time
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Any, Optional

# pylint: disable=import-error
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request

# pylint: enable=import-error
import config
from utils import resolve_camera_url, verify_secret

if TYPE_CHECKING:
    from camera_receiver import AppState

logger = logging.getLogger(config.app_name)

router = APIRouter()


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
    # Lazy import avoids circular dependency and preserves monkeypatching on camera_receiver
    import camera_receiver  # pylint: disable=import-outside-toplevel

    verify_secret(secret, x_webhook_secret)

    client_host = request.client.host if request.client else None
    client_port = request.client.port if request.client else "unknown"
    headers = dict(request.headers)
    camera_base_url = resolve_camera_url(client_host)

    logger.info(
        "Webhook request from %s:%s -> target camera %s | Method: %s | URL: %s | Headers: %s",
        client_host or "unknown",
        client_port,
        camera_base_url,
        request.method,
        request.url,
        headers,
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
        return {
            "status": "ignored",
            "alarm_type": alarm_type or None,
            "camera_url": camera_base_url,
        }

    deps: "AppState" = request.app.state.deps
    background_tasks.add_task(
        camera_receiver.fetch_and_evaluate, deps, camera_base_url, webhook_event
    )
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

    return {
        "status": "healthy",
        "serial_connected": is_serial_ok,
        "model_loaded": is_model_loaded,
        "lock_engaged": is_lock_active,
        "admin_override": admin_override,
        "lockout_remaining_seconds": round(remaining_lockout, 1),
    }
