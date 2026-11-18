import os
from pathlib import Path

import cv2

IMAGE_PATH = Path(os.getenv(IMAGE))
LABEL_PATH = Path(os.getenv(LABEL))
OUTPUT_PATH = Path("test.jpg")
CLASS_NAMES = {0: "prey", 1: "cat"}


def draw_yolo_boxes(
    image_path: Path,
    label_path: Path,
    output_path: Path,
    class_names: dict[int, str],
) -> None:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    img_h, img_w = img.shape[:2]

    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue

            cls_id = int(float(parts[0]))
            x_c, y_c, box_w, box_h = map(float, parts[1:5])

            # Convert normalized YOLO (x_center, y_center, width, height) to pixel (x1, y1, x2, y2)
            x1 = max(0, int(round((x_c - box_w / 2.0) * img_w)))
            y1 = max(0, int(round((y_c - box_h / 2.0) * img_h)))
            x2 = min(img_w - 1, int(round((x_c + box_w / 2.0) * img_w)))
            y2 = min(img_h - 1, int(round((y_c + box_h / 2.0) * img_h)))

            label = class_names.get(cls_id, f"class_{cls_id}")
            color = (0, 0, 255) if cls_id == 0 else (0, 255, 0)  # BGR: red for prey

            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            label_y = max(y1 - 6, th + 6)
            cv2.rectangle(
                img, (x1, label_y - th - 4), (x1 + tw + 6, label_y + 2), color, -1
            )
            cv2.putText(
                img,
                label,
                (x1 + 3, label_y - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

    if not cv2.imwrite(str(output_path), img):
        raise OSError(f"Failed to write output image: {output_path}")


if __name__ == "__main__":
    draw_yolo_boxes(IMAGE_PATH, LABEL_PATH, OUTPUT_PATH, CLASS_NAMES)
