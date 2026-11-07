"""Dataset inspection, thumbnail generation, YOLO label editing, and zip export."""

import os
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import cv2
from fastapi import HTTPException
from pydantic import BaseModel, Field

# pylint: enable=import-error
import config

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
THUMB_MAX_WIDTH = 360
_ZIP_CHUNK_SIZE = 64 * 1024


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
    """List captured images newest-first with parsed YOLO boxes and filter counts."""
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

    prey_ids = set(getattr(config, "prey_class_ids", {1}))
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
    """Return full-resolution image bytes or a downscaled JPEG thumbnail."""
    img_path = _safe_image_path(filename)
    if not thumb:
        return img_path.read_bytes()

    frame = cv2.imread(str(img_path))
    if frame is None:
        return img_path.read_bytes()

    height, width = frame.shape[:2]
    if width > THUMB_MAX_WIDTH:
        new_h = max(1, int(height * (THUMB_MAX_WIDTH / width)))
        frame = cv2.resize(
            frame, (THUMB_MAX_WIDTH, new_h), interpolation=cv2.INTER_AREA
        )

    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    return encoded.tobytes() if ok else img_path.read_bytes()


# pylint: enable=no-member


def save_image_labels(filename: str, boxes: list[YoloBox]) -> list[dict[str, Any]]:
    """Atomically write normalized YOLO label lines for an existing image."""
    img_path = _safe_image_path(filename)
    label_path = _label_path_for(img_path)
    label_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"{box.cls} {box.x:.6f} {box.y:.6f} {box.w:.6f} {box.h:.6f}" for box in boxes
    ]
    content = ("\n".join(lines) + "\n") if lines else ""

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=label_path.parent,
        prefix=f".{label_path.name}.",
        delete=False,
    ) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    os.replace(tmp_path, label_path)
    return parse_yolo_labels(label_path)


def delete_dataset_item(filename: str) -> None:
    """Delete both the image file and its corresponding YOLO label file."""
    img_path = _safe_image_path(filename)
    label_path = _label_path_for(img_path)
    img_path.unlink(missing_ok=True)
    label_path.unlink(missing_ok=True)


def iter_dataset_zip() -> Iterator[bytes]:
    """Stream a YOLO-formatted dataset ZIP via a temporary file without buffering in RAM."""
    images_dir = Path(config.images_dir)
    labels_dir = Path(config.labels_dir)

    with tempfile.NamedTemporaryFile(prefix="onlycats-dataset-", suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(
                "data.yaml",
                "path: .\ntrain: images\nval: images\nnames:\n  0: cat\n  1: prey\n",
            )
            if images_dir.is_dir():
                for img_path in sorted(images_dir.iterdir()):
                    if not img_path.is_file() or img_path.suffix.lower() not in {
                        ".jpg",
                        ".jpeg",
                        ".png",
                    }:
                        continue
                    zf.write(img_path, arcname=f"images/{img_path.name}")
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
