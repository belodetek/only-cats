"""Pre-populate YOLO .txt files for new images using weights/best.pt at low confidence."""

from pathlib import Path

# pylint: disable=import-error
from ultralytics import YOLO

# pylint: enable=import-error

WEIGHTS = Path("../runs/detect/prey_runs/yolo11_prey/weights/best.pt")
IMAGES_DIR = Path("images")
LABELS_DIR = Path("labels")
IMGSZ = 1280
CONF_THRESHOLD = 0.20
OVERWRITE_EXISTING = False  # Set True to re-draft even if a non-empty .txt already exists

model = YOLO(str(WEIGHTS))
LABELS_DIR.mkdir(parents=True, exist_ok=True)

images = sorted(
    p for p in IMAGES_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
)
print(f"Found {len(images)} image(s) in {IMAGES_DIR.resolve()}")

for img_path in images:
    lbl_path = LABELS_DIR / f"{img_path.stem}.txt"

    if not OVERWRITE_EXISTING and lbl_path.exists() and lbl_path.stat().st_size > 0:
        print(f"Skipping {img_path.name}: non-empty label already exists ({lbl_path.name})")
        continue

    results = model.predict(
        source=str(img_path), imgsz=IMGSZ, conf=CONF_THRESHOLD, verbose=False
    )
    top = results[0]

    lines = []
    if top.boxes is not None and len(top.boxes) > 0:
        for cls_id, box in zip(
            top.boxes.cls.cpu().numpy().astype(int), top.boxes.xywhn.cpu().numpy()
        ):
            xc, yc, bw, bh = box
            lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")

    lbl_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"{img_path.name}: drafted {len(lines)} box(es) -> {lbl_path.name}")