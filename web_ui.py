"""Web UI router for manual lock/unlock controls, diagnostics, and camera redirect."""

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

# pylint: disable=import-error
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

# pylint: enable=import-error
import config
from dataset import (
    LabelUpdatePayload,
    build_dataset_zip,
    delete_dataset_item,
    get_image_bytes,
    list_dataset_items,
    save_image_labels,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

router = APIRouter(tags=["web-ui"])


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
    html = INDEX_HTML.read_text(encoding="utf-8").replace(
        "__ASSET_V__", _compute_asset_version()
    )
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache"},
    )


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
async def ui_dataset_export_zip() -> Response:
    """Download all captured images and YOLO labels as a training-ready ZIP."""
    archive = build_dataset_zip()
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="only-cats-dataset.zip"'},
    )
