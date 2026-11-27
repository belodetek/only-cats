#!/usr/bin/env python3
"""Run YOLO cascade inference against a single image and report prey match status."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = next(
    (
        p
        for p in Path(__file__).resolve().parents
        if (p / "src" / "config.py").is_file()
    ),
    None,
)
if REPO_ROOT and str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import cv2
import numpy as np
from ultralytics import YOLO

# pylint: disable=wrong-import-position,import-error
import config
from vision import (CascadeConfig, _locate_cat_crops, compute_sharpness,
                    run_cascade_inference)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for model paths, image path, and thresholds."""
    parser = argparse.ArgumentParser(
        description="Run two-stage YOLO prey detection on a single image."
    )
    parser.add_argument(
        "--model",
        "-m",
        type=Path,
        default="../runs/detect/prey_runs/yolo11_prey/weights/best.pt",
        help="Path to Stage 2 prey YOLO model weights (.pt file or OpenVINO directory)",
    )
    parser.add_argument(
        "--cat-model",
        type=Path,
        default="../runs/detect/prey_runs/yolo11_prey/weights/yolo26s_int8_openvino_model",
        help="Path to Stage 1 cat-gate YOLO weights (default: %(default)s)",
    )
    parser.add_argument(
        "--no-cascade",
        action="store_true",
        help="Disable Stage 1 cat-crop gate and run Stage 2 on the full frame",
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
        help=f"Stage 2 prey confidence threshold (default: {config.conf_threshold})",
    )
    parser.add_argument(
        "--cat-conf",
        type=float,
        default=config.cat_conf_threshold,
        help=f"Stage 1 cat-gate confidence threshold (default: {config.cat_conf_threshold})",
    )
    return parser.parse_args()


def main() -> int:
    """Load models, evaluate single image via cascade, print summary, and return exit status."""
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
    cat_model = None
    if not args.no_cascade:
        if args.cat_model.exists():
            cat_model = YOLO(str(args.cat_model), task="detect")
        else:
            print(
                f"WARN: Cat gate model not found at {args.cat_model}; falling back to Stage 2 only.",
                file=sys.stderr,
            )

    cascade = CascadeConfig(cat_model=cat_model, cat_conf=args.cat_conf)
    img_array = np.frombuffer(raw_bytes, dtype=np.uint8)
    img, fused = run_cascade_inference(
        model, img_array, conf=args.conf, cascade=cascade
    )

    if img is None:
        print(f"ERROR: Failed to decode image: {args.image}", file=sys.stderr)
        return 2

    detections = [
        (
            model.names.get(det.cls, str(det.cls)),
            det.confidence,
            [round(det.x, 4), round(det.y, 4), round(det.w, 4), round(det.h, 4)],
        )
        for det in fused
    ]

    matched = any(cls_name in config.target_classes for cls_name, _, _ in detections)

    if cat_model is None:
        stage1_summary = "disabled (Stage 2 full-frame)"
    else:
        crops = _locate_cat_crops(cv2.imdecode(img_array, cv2.IMREAD_COLOR), cascade)
        if crops:
            stage1_summary = f"{args.cat_model} -> {len(crops)} crop(s) {crops}"
        else:
            stage1_summary = (
                f"{args.cat_model} -> 0 cats >= {args.cat_conf:.0%} "
                "(fell back to Stage 2 full-frame)"
            )

    print(f"Image:      {args.image}")
    print(f"Model:      {args.model}")
    print(f"Cat Gate:   {stage1_summary}")
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
