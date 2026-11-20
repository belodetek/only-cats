"""Web UI router for manual lock/unlock controls, diagnostics, and camera redirect."""

from pathlib import Path

# pylint: disable=import-error
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

# pylint: enable=import-error
import config

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

router = APIRouter(tags=["web-ui"])


@router.get("/", include_in_schema=False)
async def ui_root() -> FileResponse:
    """Serve the responsive web control interface at root (/)."""
    return FileResponse(INDEX_HTML)


@router.get("/ui/config")
async def get_ui_config() -> dict[str, str]:
    """Expose non-secret UI configuration values to the frontend."""
    return {"dispenser_url": config.dispenser_url}


@router.post("/ui/lock")
async def ui_force_lock(request: Request) -> dict:
    """Trigger persistent admin lockout from the web UI."""
    deps = request.app.state.deps
    if not deps or not deps.controller:
        raise HTTPException(status_code=503, detail="Lock controller not initialized")
    deps.controller.admin_lock()
    return {"status": "locked", "admin_override": "locked"}


@router.post("/ui/unlock")
async def ui_force_unlock(request: Request) -> dict:
    """Force persistent admin unlock from the web UI."""
    deps = request.app.state.deps
    if not deps or not deps.controller:
        raise HTTPException(status_code=503, detail="Lock controller not initialized")
    deps.controller.admin_unlock()
    return {"status": "unlocked", "admin_override": "unlocked"}
