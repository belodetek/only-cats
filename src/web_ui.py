"""Web UI router for manual lock/unlock controls, diagnostics, and camera redirect."""

import hashlib
import html
from pathlib import Path
from urllib.parse import urlsplit

# pylint: disable=import-error
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import config
from dataset import (
    LabelUpdatePayload,
    delete_dataset_item,
    get_image_bytes,
    iter_dataset_zip,
    list_dataset_items,
    save_image_labels,
)
from metrics import METRICS

# pylint: enable=import-error

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ERROR_HTML = STATIC_DIR / "error.html"

_ERROR_COPY = {
    401: ("Unauthorized", "Authentication is required to access the cat flap."),
    403: ("Access Denied", "Contraband detected — you do not have permission here."),
    404: ("Page Not Found", "Nothing behind this flap. The page may have moved."),
    500: ("Server Error", "Something went wrong inside the controller."),
}

router = APIRouter(tags=["web-ui"])


def render_error_response(
    request: Request, status_code: int, detail: str = ""
) -> HTMLResponse | JSONResponse:
    """Return friendly HTML for browser requests and standard JSON for API clients."""
    if "text/html" not in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=status_code, content={"detail": detail or "Error"}
        )

    title, default_msg = _ERROR_COPY.get(
        status_code, ("Request Error", detail or "Unable to complete request.")
    )
    message = (
        html.escape(detail)
        if detail and status_code not in _ERROR_COPY
        else default_msg
    )
    page = (
        ERROR_HTML.read_text(encoding="utf-8")
        .replace("__CODE__", str(status_code))
        .replace("__TITLE__", html.escape(title))
        .replace("__MESSAGE__", message)
    )
    return HTMLResponse(content=page, status_code=status_code)


def _compute_asset_version() -> str:
    """Compute a short content hash across static JS/CSS assets for cache-busting."""
    digest = hashlib.sha256()
    for name in ("app.js", "styles.css"):
        asset = STATIC_DIR / name
        if asset.is_file():
            digest.update(asset.read_bytes())
    return digest.hexdigest()[:8]


@router.get("/", include_in_schema=False)
async def ui_root() -> HTMLResponse:
    """Serve the responsive web control interface with fingerprinted asset URLs."""
    html_text = INDEX_HTML.read_text(encoding="utf-8").replace(
        "__ASSET_V__", _compute_asset_version()
    )
    return HTMLResponse(
        content=html_text,
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/error/{code}", include_in_schema=False)
async def ui_error_page(request: Request, code: int) -> HTMLResponse:
    """Render static friendly error page for reverse-proxy error rewrites."""
    safe_code = code if 400 <= code <= 599 else 500
    return render_error_response(
        request, safe_code
    )  # returns HTML when Accept includes text/html


@router.get("/ui/metrics")
async def ui_metrics_snapshot() -> dict:
    """Return JSON telemetry snapshot for the Web UI drawer."""
    return METRICS.snapshot_json()


@router.get("/ui/config")
async def get_ui_config() -> dict[str, str]:
    """Expose non-secret UI configuration values to the frontend."""
    raw_url = getattr(config, "dispenser_url", "").strip()
    if raw_url:
        parsed = urlsplit(raw_url)
        dispenser_url = (
            f"{parsed.scheme}://{parsed.netloc}/"
            if parsed.scheme and parsed.netloc
            else raw_url
        )
    else:
        dispenser_url = ""
    return {
        "dispenser_url": dispenser_url,
        "app_version": getattr(config, "app_version", "0.0.0"),
        "repo_url": getattr(config, "repo_url", ""),
    }


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


@router.get("/ui/dataset/items")
async def ui_dataset_items(
    filter_mode: str = Query("all", alias="filter", pattern="^(all|prey|empty)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    """List captured training images and YOLO bounding boxes."""
    return list_dataset_items(filter_mode=filter_mode, offset=offset, limit=limit)


@router.get("/ui/dataset/image/{filename}")
async def ui_dataset_image(filename: str, thumb: bool = Query(False)) -> Response:
    """Serve a training capture JPEG or lightweight thumbnail."""
    data = get_image_bytes(filename, thumb=thumb)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.put("/ui/dataset/labels/{filename}")
async def ui_dataset_update_labels(filename: str, payload: LabelUpdatePayload) -> dict:
    """Update YOLO class IDs or bounding boxes for a captured image."""
    updated = save_image_labels(filename, payload.boxes)
    return {"filename": filename, "boxes": updated}


@router.delete("/ui/dataset/items/{filename}")
async def ui_dataset_delete_item(filename: str) -> dict:
    """Delete a captured image and its label file from the training set."""
    delete_dataset_item(filename)
    return {"deleted": filename}


@router.get("/ui/dataset/export.zip")
def export_dataset_zip():
    """Stream the YOLO training dataset archive without buffering the full ZIP in RAM."""
    return StreamingResponse(
        iter_dataset_zip(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="only-cats-dataset.zip"'},
    )
