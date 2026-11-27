# pylint: disable=no-member
"""YOLO inference and OpenVINO model metadata helpers."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import cv2
import numpy as np
import yaml
from ultralytics import YOLO

# pylint: enable=import-error

# MS COCO class IDs for Stage 1 animal ROI gating (15=cat, 16=dog)
COCO_ANIMAL_CLASSES = [15, 16]


@dataclass(frozen=True)
class FusedDetection:
    """Normalized [0, 1] full-frame detection produced by single-stage or cascade inference."""

    cls: int
    confidence: float
    x: float  # center x (normalized)
    y: float  # center y (normalized)
    w: float  # width (normalized)
    h: float  # height (normalized)


@dataclass(frozen=True)
class CascadeConfig:
    """Stage 1 cat-gate model and crop parameters for two-stage cascade inference."""

    cat_model: YOLO | None = None
    cat_conf: float = 0.20
    pad_ratio: float = 0.20


def load_model_metadata(weights_path: str | Path) -> dict[str, Any]:
    """Read Ultralytics OpenVINO metadata.yaml from weights_path directory if present."""
    base = Path(weights_path)
    meta_file = (
        base / "metadata.yaml" if base.is_dir() else base.parent / "metadata.yaml"
    )
    if not meta_file.is_file():
        return {}
    try:
        parsed = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def format_model_date(raw_date: Any) -> str | None:
    """Return YYYY-MM-DD from an ISO-8601 metadata date string, or None if missing."""
    if not raw_date:
        return None
    text = str(raw_date).strip()
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        return text[:10] if len(text) >= 10 else text


def compute_sharpness(image_bytes: bytes) -> float:
    """Return variance of the Laplacian (higher = sharper, lower = blurrier)."""
    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    gray = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return 0.0
    # Resize to a fixed width so the threshold behaves consistently across camera resolutions
    h, w = gray.shape
    if w > 640:
        scale = 640.0 / w
        gray = cv2.resize(gray, (640, int(h * scale)), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _box_to_fused(
    xyxy: Any,
    score: float,
    cls_id: int,
    offset_xy: tuple[int, int],
    full_wh: tuple[int, int],
) -> FusedDetection | None:
    """Map one pixel xyxy box plus crop offset into a full-frame normalized FusedDetection."""
    ox, oy = offset_xy
    fw, fh = full_wh
    gx1 = max(0.0, min(float(fw), float(xyxy[0]) + ox))
    gy1 = max(0.0, min(float(fh), float(xyxy[1]) + oy))
    gx2 = max(0.0, min(float(fw), float(xyxy[2]) + ox))
    gy2 = max(0.0, min(float(fh), float(xyxy[3]) + oy))
    bw, bh = gx2 - gx1, gy2 - gy1
    if bw <= 0.0 or bh <= 0.0:
        return None
    return FusedDetection(
        cls=int(cls_id),
        confidence=float(score),
        x=((gx1 + gx2) / 2.0) / fw,
        y=((gy1 + gy2) / 2.0) / fh,
        w=bw / fw,
        h=bh / fh,
    )


def _extract_detections(
    results: Any,
    offset_xy: tuple[int, int] = (0, 0),
    full_wh: tuple[int, int] | None = None,
) -> list[FusedDetection]:
    """Convert Ultralytics Results into full-frame normalized FusedDetection items."""
    detections: list[FusedDetection] = []
    for res in results or []:
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        frame_wh = (
            full_wh if full_wh is not None else (res.orig_shape[1], res.orig_shape[0])
        )
        if frame_wh[0] <= 0 or frame_wh[1] <= 0:
            continue
        triples = zip(
            boxes.xyxy.cpu().numpy(),
            boxes.conf.cpu().numpy(),
            boxes.cls.cpu().numpy().astype(int),
        )
        for xyxy, score, cls_id in triples:
            det = _box_to_fused(xyxy, float(score), int(cls_id), offset_xy, frame_wh)
            if det is not None:
                detections.append(det)
    return detections


def _boxes_iou(box_a: FusedDetection, box_b: FusedDetection) -> float:
    """Compute Intersection-over-Union between two normalized center-format detections."""
    ax1, ay1 = box_a.x - box_a.w / 2.0, box_a.y - box_a.h / 2.0
    ax2, ay2 = box_a.x + box_a.w / 2.0, box_a.y + box_a.h / 2.0
    bx1, by1 = box_b.x - box_b.w / 2.0, box_b.y - box_b.h / 2.0
    bx2, by2 = box_b.x + box_b.w / 2.0, box_b.y + box_b.h / 2.0

    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0, min(ay2, by2) - max(ay1, by1)
    )
    union = (box_a.w * box_a.h) + (box_b.w * box_b.h) - inter
    return (inter / union) if union > 0.0 else 0.0


def _deduplicate_detections(
    detections: list[FusedDetection], iou_threshold: float = 0.5
) -> list[FusedDetection]:
    """Suppress duplicate boxes of the same class when two padded cat crops overlap."""
    kept: list[FusedDetection] = []
    for cand in sorted(detections, key=lambda d: d.confidence, reverse=True):
        if not any(
            prev.cls == cand.cls and _boxes_iou(prev, cand) >= iou_threshold
            for prev in kept
        ):
            kept.append(cand)
    return kept


def _pad_crop_box(
    xyxy: Any, pad_ratio: float, full_wh: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    """Expand a pixel xyxy box by pad_ratio and clamp to full_wh bounds."""
    full_w, full_h = full_wh
    x1, y1, x2, y2 = xyxy
    pad_x = (x2 - x1) * pad_ratio
    pad_y = (y2 - y1) * pad_ratio
    cx1, cy1 = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
    cx2, cy2 = min(full_w, int(x2 + pad_x)), min(full_h, int(y2 + pad_y))
    return (cx1, cy1, cx2, cy2) if cx2 > cx1 and cy2 > cy1 else None


def _locate_cat_crops(
    img: np.ndarray, cascade: CascadeConfig
) -> list[tuple[int, int, int, int]]:
    """Run Stage 1 detector and return padded pixel crops around detected cats/dogs."""
    if cascade.cat_model is None:
        return []
    full_wh = (img.shape[1], img.shape[0])
    gate_results = cascade.cat_model.predict(
        source=img,
        classes=COCO_ANIMAL_CLASSES,
        conf=cascade.cat_conf,
        verbose=False,
    )
    crops: list[tuple[int, int, int, int]] = []
    for res in gate_results or []:
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        for xyxy in boxes.xyxy.cpu().numpy():
            crop = _pad_crop_box(xyxy, cascade.pad_ratio, full_wh)
            if crop is not None:
                crops.append(crop)
    return crops


def run_cascade_inference(
    prey_model: YOLO,
    img_array: np.ndarray,
    conf: float,
    cascade: CascadeConfig | None = None,
) -> tuple[np.ndarray | None, list[FusedDetection]]:
    """Decode JPEG bytes and fuse full-frame + Stage 1 cat-crop prey detections."""
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        return None, []

    full_wh = (img.shape[1], img.shape[0])
    full_results = prey_model.predict(source=img, conf=conf, verbose=False)
    merged = _extract_detections(full_results, full_wh=full_wh)

    for cx1, cy1, cx2, cy2 in _locate_cat_crops(img, cascade or CascadeConfig()):
        crop_results = prey_model.predict(
            source=img[cy1:cy2, cx1:cx2], conf=conf, verbose=False
        )
        merged.extend(
            _extract_detections(crop_results, offset_xy=(cx1, cy1), full_wh=full_wh)
        )

    return img, _deduplicate_detections(merged)


def run_inference(model: YOLO, img_array: np.ndarray, conf: float):
    """Decode JPEG bytes and run YOLO object detection (legacy single-model signature)."""
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        return None, None
    results = model.predict(source=img, conf=conf, verbose=False)
    return img, results
