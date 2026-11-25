#!/usr/bin/env python3
"""Run YOLO inference against a single image and report prey match status."""

import argparse
import sys
from pathlib import Path

SRC_DIR = next(
    (
        p / "src"
        for p in Path(__file__).resolve().parents
        if (p / "src" / "config.py").is_file()
    ),
    None,
)
if SRC_DIR and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# pylint: disable=wrong-import-position,import-error
import config
import numpy as np
from ultralytics import YOLO
from vision import compute_sharpness, run_inference


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for model path, image path, and confidence."""
    parser = argparse.ArgumentParser(
        description="Run YOLO prey detection on a single image."
    )
    parser.add_argument(
        "--model",
        "-m",
        type=Path,
        default="../runs/detect/prey_runs/yolo11_prey/weights/best.pt",
        help="Path to YOLO model weights (.pt file or OpenVINO model directory)",
    )
    parser.add_argument(
        "--image",
        "-i",
        type=Path,
        required=True,
        help="Path to input image (.jpg, .jpeg, .png)",
    )
    parser.add_argument(
        "--conf",
        "-c",
        type=float,
        default=config.conf_threshold,
        help=f"Confidence threshold (default: {config.conf_threshold})",
    )
    return parser.parse_args()


def main() -> int:
    """Load model, evaluate single image, print summary, and return exit status."""
    args = parse_args()

    if not args.model.exists():
        print(f"ERROR: Model not found: {args.model}", file=sys.stderr)
        return 2
    if not args.image.is_file():
        print(f"ERROR: Image not found: {args.image}", file=sys.stderr)
        return 2

    raw_bytes = args.image.read_bytes()
    sharpness = compute_sharpness(raw_bytes)

    model = YOLO(str(args.model), task="detect")
    img_array = np.frombuffer(raw_bytes, dtype=np.uint8)
    img, results = run_inference(model, img_array, conf=args.conf)

    if img is None:
        print(f"ERROR: Failed to decode image: {args.image}", file=sys.stderr)
        return 2

    top_result = results[0] if results else None
    detections: list[tuple[str, float, list[float]]] = []
    if top_result is not None and top_result.boxes is not None:
        for cls_id, conf, xywhn in zip(
            top_result.boxes.cls.cpu().numpy().astype(int),
            top_result.boxes.conf.cpu().numpy(),
            top_result.boxes.xywhn.cpu().numpy(),
        ):
            cls_name = model.names[int(cls_id)]
            detections.append(
                (cls_name, float(conf), [round(float(v), 4) for v in xywhn])
            )

    matched = any(cls_name in config.target_classes for cls_name, _, _ in detections)

    print(f"Image:      {args.image}")
    print(f"Model:      {args.model}")
    print(f"Sharpness:  {sharpness:.1f} (threshold: {config.min_blur_variance})")
    print(f"Matched:    {matched}")
    if detections:
        for cls_name, conf, bbox in detections:
            tag = " [TARGET]" if cls_name in config.target_classes else ""
            print(f"  - {cls_name}: {conf:.2%} xywhn={bbox}{tag}")
    else:
        print(f"  - No detections >= {args.conf:.0%}")

    return 0 if matched else 1


if __name__ == "__main__":
    sys.exit(main())
