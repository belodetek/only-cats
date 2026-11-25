# pylint: disable=no-member
"""YOLO inference and OpenVINO model metadata helpers."""

from datetime import datetime
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import cv2
import numpy as np
import yaml
from ultralytics import YOLO

# pylint: enable=import-error


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


def run_inference(model: YOLO, img_array: np.ndarray, conf: float):
    """Decode JPEG bytes and run YOLO object detection."""
    # pylint: disable=no-member
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    # pylint: enable=no-member
    if img is None:
        return None, None
    results = model.predict(source=img, conf=conf, verbose=False)
    return img, results
