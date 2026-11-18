"""Fine-tune best.pt on fine-tune/{images,labels} and export to OpenVINO IR."""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml
from ultralytics import YOLO

BASE_WEIGHTS = Path("../runs/detect/prey_runs/yolo11_prey/weights/best.pt")
OPENVINO_OUT_DIR = Path(
    "../runs/detect/prey_runs/yolo11_prey/weights/best_openvino_model"
)
DATASET_DIR = Path(".").resolve()
DATASET_YAML = DATASET_DIR / "dataset.yaml"
IMGSZ = 1280  # Matches 4K Reolink snapshots; keep aligned with model.predict(imgsz=...)


def validate_dataset(dataset_dir: Path, yaml_path: Path) -> None:
    """Ensure dataset.yaml points cleanly to fine-tune/{images,labels} and verify counts."""
    images_dir = dataset_dir / "images"
    labels_dir = dataset_dir / "labels"

    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise FileNotFoundError(
            f"Expected 'images' and 'labels' directories inside {dataset_dir}"
        )

    images = [
        p for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    if not images:
        raise ValueError(f"No images found in {images_dir}")

    positives = 0
    negatives = 0
    for img_path in images:
        lbl_path = labels_dir / f"{img_path.stem}.txt"
        if not lbl_path.exists():
            # Create empty 0-byte label file so Ultralytics explicitly treats it as a background sample
            lbl_path.write_text("", encoding="utf-8")
            negatives += 1
        elif lbl_path.read_text(encoding="utf-8").strip():
            positives += 1
        else:
            negatives += 1

    print(
        f"Dataset verified: {len(images)} total images "
        f"({positives} positive with prey labels, {negatives} negative/background)"
    )

    # Ensure dataset.yaml has absolute 'path' so Ultralytics resolves it from any working directory
    existing_names = {0: "prey"}
    if yaml_path.exists():
        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded.get("names"), dict):
            existing_names = loaded["names"]

    yaml_payload = {
        "path": str(dataset_dir),
        "train": "images",
        "val": "images",
        "names": existing_names,
    }
    yaml_path.write_text(
        yaml.safe_dump(yaml_payload, sort_keys=False), encoding="utf-8"
    )


def backup_existing_weights(weights_path: Path) -> None:
    """Save a timestamped backup of best.pt before overwriting it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = weights_path.with_name(f"{weights_path.stem}_backup_{stamp}.pt")
    shutil.copy2(weights_path, backup_path)
    print(f"Backed up previous weights -> {backup_path}")


def main() -> None:
    if not BASE_WEIGHTS.exists():
        raise FileNotFoundError(f"Base weights not found at {BASE_WEIGHTS}")

    validate_dataset(DATASET_DIR, DATASET_YAML)
    backup_existing_weights(BASE_WEIGHTS)

    # 1. Fine-tune from existing best.pt
    model = YOLO(str(BASE_WEIGHTS))
    results = model.train(
        data=str(DATASET_YAML),
        epochs=60,
        imgsz=IMGSZ,
        batch=4,
        rect=False,  # Handles varied snapshot dimensions (~3800x2100) + mosaic augmentation
        lr0=0.0005,  # Gentle learning rate for a 12-image fine-tune batch
        lrf=0.01,
        freeze=10,  # Freeze backbone layers to prevent overfitting on small sample count
        mosaic=0.8,
        mixup=0.0,
        scale=0.5,
        fliplr=0.5,
        patience=20,
        project="runs/fine_tune",
        name="patio_update",
        exist_ok=True,
    )

    updated_pt = Path(results.save_dir) / "weights" / "best.pt"
    if not updated_pt.exists():
        raise FileNotFoundError(f"Fine-tuned checkpoint not found at {updated_pt}")

    # 2. Update weights/best.pt with the newly fine-tuned checkpoint
    shutil.copy2(updated_pt, BASE_WEIGHTS)
    print(f"Updated {BASE_WEIGHTS} from {updated_pt}")

    # 3. Export updated best.pt to OpenVINO IR
    finetuned_model = YOLO(str(BASE_WEIGHTS))
    exported_dir = Path(
        finetuned_model.export(
            format="openvino",
            imgsz=IMGSZ,
            half=False,
        )
    )
    print(f"Exported OpenVINO model -> {OPENVINO_OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
