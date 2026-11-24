"""YOLO inference helpers."""

# pylint: disable=import-error
import cv2
import numpy as np
from ultralytics import YOLO

# pylint: enable=import-error


def run_inference(model: YOLO, img_array: np.ndarray, conf: float):
    """Decode JPEG bytes and run YOLO object detection."""
    # pylint: disable=no-member
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    # pylint: enable=no-member
    if img is None:
        return None, None
    results = model.predict(source=img, conf=conf, verbose=False)
    return img, results
