"""Generate boxed and zoomed verification previews for all non-empty YOLO labels."""

from pathlib import Path

# pylint: disable=import-error
import cv2

# pylint: enable=import-error

IMAGES_DIR = Path("images")
LABELS_DIR = Path("labels")
VERIFY_DIR = Path("verify")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

VERIFY_DIR.mkdir(parents=True, exist_ok=True)


def find_matching_image(base: str) -> Path | None:
    """Find image in IMAGES_DIR matching the label stem across common extensions."""
    for ext in IMAGE_EXTENSIONS:
        candidate = IMAGES_DIR / f"{base}{ext}"
        if candidate.is_file():
            return candidate
    return None


for lbl_path in sorted(LABELS_DIR.glob("*.txt")):
    lines = [
        line.strip()
        for line in lbl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        continue

    stem = lbl_path.stem
    img_path = find_matching_image(stem)
    if img_path is None:
        print(f"Skipping {lbl_path.name}: no matching image in {IMAGES_DIR}")
        continue

    img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"Skipping {img_path.name}: failed to decode image")
        continue

    h, w = img.shape[:2]
    annotated = img.copy()
    thickness = max(2, int(round(w / 640)))
    font_scale = max(0.6, w / 1600.0)
    boxes_drawn = 0

    for raw_line in lines:
        parts = raw_line.split()
        if len(parts) < 5:
            continue

        cls_id = int(float(parts[0]))
        xc, yc, bw, bh = map(float, parts[1:5])

        x1 = max(0, int(round((xc - bw / 2.0) * w)))
        y1 = max(0, int(round((yc - bh / 2.0) * h)))
        x2 = min(w - 1, int(round((xc + bw / 2.0) * w)))
        y2 = min(h - 1, int(round((yc + bh / 2.0) * h)))

        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), thickness)
        cv2.putText(
            annotated,
            f"prey ({cls_id})",
            (x1, max(y1 - 10, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 255),
            thickness,
            cv2.LINE_AA,
        )

        boxes_drawn += 1
        zoom_suffix = f"_zoom_{boxes_drawn}" if boxes_drawn > 1 else "_zoom"
        pad_x = max(120, int((x2 - x1) * 1.5))
        pad_y = max(120, int((y2 - y1) * 0.8))
        cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
        cx2, cy2 = min(w, x2 + pad_x), min(h, y2 + pad_y)
        cv2.imwrite(
            str(VERIFY_DIR / f"{stem}{zoom_suffix}.jpg"), annotated[cy1:cy2, cx1:cx2]
        )

    if boxes_drawn > 0:
        out_path = VERIFY_DIR / f"{stem}_boxed.jpg"
        cv2.imwrite(str(out_path), annotated)
        print(
            f"Verified {img_path.name} ({w}x{h}, {boxes_drawn} box(es)) -> {out_path}"
        )
