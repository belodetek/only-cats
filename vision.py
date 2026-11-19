# pylint: disable=too-many-locals
"""YOLO inference and dataset image/label persistence helpers."""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

# pylint: disable=import-error
import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.engine.results import Results

# pylint: enable=import-error
import config

logger = logging.getLogger(config.app_name)


def run_inference(model: YOLO, img_array: np.ndarray, conf: float):
    """Decode JPEG bytes and run YOLO object detection."""
    # pylint: disable=no-member
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    # pylint: enable=no-member
    if img is None:
        return None, None
    results = model.predict(source=img, conf=conf, verbose=False)
    return img, results


def persist_training_pair(
    img: np.ndarray,
    result: Optional[Results],
    prefix: str = "prey",
) -> Optional[tuple[str, str]]:
    """Persist raw image and normalized YOLO bounding boxes, returning saved paths."""
    try:
        base_name = (
            f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
        )
        img_path = os.path.join(config.images_dir, f"{base_name}.jpg")
        label_path = os.path.join(config.labels_dir, f"{base_name}.txt")

        # pylint: disable=no-member
        success = cv2.imwrite(img_path, img)
        # pylint: enable=no-member

        if not success:
            logger.error("Failed to write image snapshot to %s", img_path)
            return None

        label_lines: list[str] = []
        if result is not None and result.boxes is not None and len(result.boxes) > 0:
            # xywhn provides normalized (x_center, y_center, width, height) in range [0.0, 1.0]
            boxes_xywhn = result.boxes.xywhn.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy().astype(int)

            for cls_id, box in zip(classes, boxes_xywhn):
                x_c, y_c, width, height = box
                label_lines.append(
                    f"{cls_id} {x_c:.6f} {y_c:.6f} {width:.6f} {height:.6f}\n"
                )

        with open(label_path, "w", encoding="utf-8") as label_file:
            label_file.writelines(label_lines)

        logger.info("Persisted training pair: %s and %s", img_path, label_path)
        return img_path, label_path

    except OSError as exc:
        logger.error("Filesystem error while persisting training pair: %s", exc)
        return None
