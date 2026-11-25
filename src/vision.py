# pylint: disable=no-member
"""YOLO inference helpers."""

# pylint: disable=import-error
import cv2
import numpy as np
from ultralytics import YOLO

# pylint: enable=import-error


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
