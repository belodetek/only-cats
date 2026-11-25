"""Dataset inspection, metadata stripping, metadata storage, label editing, and zip export."""

import io
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import cv2
from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

# pylint: enable=import-error
import config

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
THUMB_MAX_WIDTH = 360
_ZIP_CHUNK_SIZE = 64 * 1024

logger = logging.getLogger(config.app_name)


class PurgeDatasetPayload(BaseModel):  # pylint: disable=too-few-public-methods
    """Confirmation payload required to permanently purge the dataset."""

    confirm: str


class YoloBox(BaseModel):  # pylint: disable=too-few-public-methods
    """Normalized YOLO bounding box (center-x, center-y, width, height in [0, 1])."""

    cls: int = Field(ge=0, le=32)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)


class LabelUpdatePayload(BaseModel):  # pylint: disable=too-few-public-methods
    """Request payload for updating YOLO labels on a captured training image."""

    boxes: list[YoloBox]


def purge_dataset() -> dict[str, int]:
    """Delete all training images, YOLO .txt labels, and .json metadata files."""
    deleted_images = 0
    deleted_labels = 0
    deleted_meta = 0

    images_dir = Path(config.images_dir)
    if images_dir.is_dir():
        for path in images_dir.iterdir():
            if (
                path.is_file()
                and not path.name.startswith(".")
                and path.suffix.lower() in ALLOWED_IMAGE_EXTS
            ):
                path.unlink(missing_ok=True)
                deleted_images += 1

    labels_dir = Path(config.labels_dir)
    if labels_dir.is_dir():
        for path in labels_dir.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            suffix = path.suffix.lower()
            if suffix == ".txt":
                path.unlink(missing_ok=True)
                deleted_labels += 1
            elif suffix == ".json":
                path.unlink(missing_ok=True)
                deleted_meta += 1

    logger.warning(
        "Dataset purged: %d images, %d labels, %d metadata files deleted.",
        deleted_images,
        deleted_labels,
        deleted_meta,
    )
    return {
        "deleted_images": deleted_images,
        "deleted_labels": deleted_labels,
        "deleted_meta": deleted_meta,
    }


def strip_image_metadata(raw_bytes: bytes, quality: int = 92) -> bytes:
    """Decode image bytes and re-encode clean pixel data with all EXIF/XMP/COM stripped."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        # Apply any EXIF orientation tag to pixels BEFORE stripping EXIF
        clean_img = ImageOps.exif_transpose(img)
        if clean_img.mode not in ("RGB", "L"):
            clean_img = clean_img.convert("RGB")

        out = io.BytesIO()
        # Passing no exif=, icc_profile=, or pnginfo= writes a completely metadata-free file
        clean_img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
    """Write bytes to target_path atomically via a temp file in the same directory."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target_path.parent,
        prefix=f".{target_path.name}.",
        delete=False,
    ) as tmp_file:
        tmp_file.write(data)
        tmp_path = Path(tmp_file.name)
    os.replace(tmp_path, target_path)


def _safe_image_path(filename: str) -> Path:
    """Resolve filename inside config.images_dir and reject path traversal."""
    if (
        Path(filename).name != filename
        or Path(filename).suffix.lower() not in ALLOWED_IMAGE_EXTS
    ):
        raise HTTPException(status_code=400, detail="Invalid image filename")
    base_dir = Path(config.images_dir).resolve()
    target = (base_dir / filename).resolve()
    if target.parent != base_dir or not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return target


def _label_path_for(image_path: Path) -> Path:
    """Return the corresponding YOLO .txt path inside config.labels_dir."""
    return Path(config.labels_dir).resolve() / f"{image_path.stem}.txt"


def _meta_path_for(image_path: Path) -> Path:
    """Return the corresponding metadata .json path inside config.labels_dir."""
    return Path(config.labels_dir).resolve() / f"{image_path.stem}.json"


def read_json_meta(meta_path: Path) -> dict[str, Any]:
    """Read webhook/inference metadata JSON if present, returning {} on missing/corrupt."""
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to parse JSON metadata at %s: %s", meta_path, exc)
        return {}

    if not isinstance(data, dict) or not data:
        logger.warning("JSON metadata is empty at %s", meta_path)
        return {}
    return data


def save_clean_capture(
    stem: str,
    raw_image_bytes: bytes,
    boxes: list[YoloBox] | None = None,
    meta: dict[str, Any] | None = None,
    quality: int = 92,
) -> Path:
    """Persist metadata-stripped JPEG, YOLO .txt labels, and optional .json metadata."""
    safe_stem = Path(stem).name
    if not safe_stem or safe_stem != stem:
        raise ValueError(f"Invalid capture stem: {stem!r}")

    images_dir = Path(config.images_dir).resolve()
    labels_dir = Path(config.labels_dir).resolve()
    img_path = images_dir / f"{safe_stem}.jpg"
    label_path = labels_dir / f"{safe_stem}.txt"
    meta_path = labels_dir / f"{safe_stem}.json"

    lines = [
        f"{box.cls} {box.x:.6f} {box.y:.6f} {box.w:.6f} {box.h:.6f}"
        for box in (boxes or [])
    ]
    label_content = ("\n".join(lines) + "\n") if lines else ""
    _atomic_write_bytes(label_path, label_content.encode("utf-8"))

    if not meta:
        logger.warning("Empty JSON metadata provided for capture %s", safe_stem)

    if meta is not None:
        _atomic_write_bytes(
            meta_path, (json.dumps(meta, indent=2, default=str) + "\n").encode("utf-8")
        )

    clean_bytes = strip_image_metadata(raw_image_bytes, quality=quality)
    _atomic_write_bytes(img_path, clean_bytes)

    return img_path


def parse_yolo_labels(label_path: Path) -> list[dict[str, Any]]:
    """Read normalized YOLO bounding boxes from a .txt file."""
    if not label_path.is_file():
        return []
    boxes: list[dict[str, Any]] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split()
        if len(parts) != 5:
            continue
        try:
            boxes.append(
                {
                    "cls": int(parts[0]),
                    "x": round(float(parts[1]), 6),
                    "y": round(float(parts[2]), 6),
                    "w": round(float(parts[3]), 6),
                    "h": round(float(parts[4]), 6),
                }
            )
        except ValueError:
            continue
    return boxes


def list_dataset_items(
    filter_mode: str = "all", offset: int = 0, limit: int = 30
) -> dict[str, Any]:
    """List captured images newest-first with YOLO boxes, metadata, and counts."""
    images_dir = Path(config.images_dir)
    if not images_dir.is_dir():
        return {"items": [], "total": 0, "counts": {"all": 0, "prey": 0, "empty": 0}}

    files = sorted(
        (
            p
            for p in images_dir.iterdir()
            if p.is_file() and p.suffix.lower() in ALLOWED_IMAGE_EXTS
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # The model only detects contraband, so every configured target class is a
    # prey class; YOLO label ids are 0-based indices over config.target_classes.
    prey_ids = set(range(len(config.target_classes)))
    counts = {"all": 0, "prey": 0, "empty": 0}
    matched: list[dict[str, Any]] = []

    for img_path in files:
        boxes = parse_yolo_labels(_label_path_for(img_path))
        has_prey = any(box["cls"] in prey_ids for box in boxes)
        is_empty = len(boxes) == 0

        counts["all"] += 1
        if has_prey:
            counts["prey"] += 1
        if is_empty:
            counts["empty"] += 1

        if filter_mode == "prey" and not has_prey:
            continue
        if filter_mode == "empty" and not is_empty:
            continue

        matched.append(
            {
                "filename": img_path.name,
                "timestamp": int(img_path.stat().st_mtime),
                "has_prey": has_prey,
                "boxes": boxes,
                "meta": read_json_meta(_meta_path_for(img_path)),
                "image_url": f"/ui/dataset/image/{img_path.name}",
                "thumb_url": f"/ui/dataset/image/{img_path.name}?thumb=1",
            }
        )

    return {
        "items": matched[offset : offset + limit],
        "total": len(matched),
        "counts": counts,
    }


# pylint: disable=no-member
def get_image_bytes(filename: str, thumb: bool = False) -> bytes:
    """Return metadata-stripped image bytes or a downscaled JPEG thumbnail."""
    img_path = _safe_image_path(filename)
    raw = img_path.read_bytes()
    if not thumb:
        try:
            return strip_image_metadata(raw)
        except OSError:
            return raw

    frame = cv2.imread(str(img_path))
    if frame is None:
        return raw

    height, width = frame.shape[:2]
    if width > THUMB_MAX_WIDTH:
        new_h = max(1, int(height * (THUMB_MAX_WIDTH / width)))
        frame = cv2.resize(
            frame, (THUMB_MAX_WIDTH, new_h), interpolation=cv2.INTER_AREA
        )

    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    return encoded.tobytes() if ok else raw


# pylint: enable=no-member


def save_image_labels(filename: str, boxes: list[YoloBox]) -> list[dict[str, Any]]:
    """Atomically write normalized YOLO label lines for an existing image."""
    img_path = _safe_image_path(filename)
    label_path = _label_path_for(img_path)

    lines = [
        f"{box.cls} {box.x:.6f} {box.y:.6f} {box.w:.6f} {box.h:.6f}" for box in boxes
    ]
    content = ("\n".join(lines) + "\n") if lines else ""
    _atomic_write_bytes(label_path, content.encode("utf-8"))
    return parse_yolo_labels(label_path)


def delete_dataset_item(filename: str) -> None:
    """Delete the image file, its YOLO label file, and its metadata JSON."""
    img_path = _safe_image_path(filename)
    label_path = _label_path_for(img_path)
    meta_path = _meta_path_for(img_path)
    img_path.unlink(missing_ok=True)
    label_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def iter_dataset_zip() -> Iterator[bytes]:
    """Stream a YOLO-formatted dataset ZIP with metadata-stripped images."""
    images_dir = Path(config.images_dir)
    labels_dir = Path(config.labels_dir)

    with tempfile.NamedTemporaryFile(prefix="onlycats-dataset-", suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(
                "data.yaml",
                "path: .\ntrain: images\nval: images\nnames:\n  0: prey\n",
            )
            if images_dir.is_dir():
                for img_path in sorted(images_dir.iterdir()):
                    if (
                        not img_path.is_file()
                        or img_path.suffix.lower() not in ALLOWED_IMAGE_EXTS
                    ):
                        continue
                    raw = img_path.read_bytes()
                    try:
                        clean_bytes = strip_image_metadata(raw)
                        zf.writestr(f"images/{img_path.stem}.jpg", clean_bytes)
                    except OSError:
                        zf.writestr(f"images/{img_path.name}", raw)

                    lbl_path = labels_dir / f"{img_path.stem}.txt"
                    lbl_text = (
                        lbl_path.read_text(encoding="utf-8")
                        if lbl_path.is_file()
                        else ""
                    )
                    zf.writestr(f"labels/{img_path.stem}.txt", lbl_text)

        tmp.seek(0)
        while chunk := tmp.read(_ZIP_CHUNK_SIZE):
            yield chunk
