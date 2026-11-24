# pylint: disable=too-many-locals
"""Unit tests for vision.py inference, EXIF metadata stripping,
and JSON metadata persistence."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

# pylint: disable=import-error
import numpy as np
from PIL import Image

# pylint: enable=import-error
import dataset
import evaluator
import vision
from tests.conftest import make_yolo_result


def _jpeg_with_exif() -> bytes:
    """Build a valid JPEG containing embedded EXIF tags to verify stripping."""
    img = Image.new("RGB", (32, 32), color=(120, 180, 220))
    exif = Image.Exif()
    exif[271] = "ReolinkTestCam"  # Make
    exif[272] = "RLC-810A-SECRET-SERIAL"  # Model
    exif[306] = "2026:11:22 10:00:00"  # DateTime
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_run_inference_decodes_valid_jpeg(sample_jpeg_bytes):
    """Verify run_inference decodes JPEG bytes and invokes model.predict."""
    mock_model = MagicMock()
    expected_result = [make_yolo_result([(0, 0.95, [0.5, 0.5, 0.2, 0.2])])]
    mock_model.predict.return_value = expected_result

    img_array = np.frombuffer(sample_jpeg_bytes, dtype=np.uint8)
    img, results = vision.run_inference(mock_model, img_array, conf=0.4)

    assert img is not None
    assert img.ndim == 3
    assert results == expected_result
    mock_model.predict.assert_called_once()
    assert mock_model.predict.call_args[1]["conf"] == 0.4


def test_run_inference_returns_none_for_corrupt_bytes():
    """Verify run_inference returns (None, None) without calling model on invalid bytes."""
    mock_model = MagicMock()
    corrupt_array = np.frombuffer(b"not-a-valid-jpeg", dtype=np.uint8)

    img, results = vision.run_inference(mock_model, corrupt_array, conf=0.5)

    assert img is None
    assert results is None
    mock_model.predict.assert_not_called()


def test_persist_training_pair_writes_image_and_normalized_labels(tmp_data_dirs):
    """Verify persist_training_pair writes .jpg and YOLO xywhn .txt files."""
    images_dir, labels_dir = tmp_data_dirs
    dummy_img = np.zeros((32, 32, 3), dtype=np.uint8)
    result = make_yolo_result(
        [
            (0, 0.92, [0.25, 0.5, 0.1, 0.2]),
            (1, 0.81, [0.75, 0.6, 0.3, 0.4]),
        ]
    )

    saved = vision.persist_training_pair(dummy_img, result, prefix="prey")

    assert saved is not None
    img_path, label_path = saved
    assert img_path.startswith(str(images_dir))
    assert label_path.startswith(str(labels_dir))

    with open(label_path, encoding="utf-8") as label_file:
        lines = label_file.read().splitlines()
    assert lines == [
        "0 0.250000 0.500000 0.100000 0.200000",
        "1 0.750000 0.600000 0.300000 0.400000",
    ]


def test_persist_training_pair_returns_none_when_directory_missing(
    tmp_data_dirs, monkeypatch
):
    """Verify persist_training_pair handles write failure cleanly by returning None."""
    images_dir, _ = tmp_data_dirs
    monkeypatch.setattr(vision.config, "images_dir", str(images_dir / "missing_subdir"))
    dummy_img = np.zeros((16, 16, 3), dtype=np.uint8)

    assert vision.persist_training_pair(dummy_img, None, prefix="train") is None


def test_persist_clean_pair_strips_exif_writes_metadata_and_keeps_yolo_zip_clean(
    tmp_data_dirs,
):
    """Verify EXIF is stripped from persisted JPEGs and webhook meta lives only in .json."""
    images_dir, labels_dir = tmp_data_dirs
    raw_exif_jpeg = _jpeg_with_exif()
    assert b"RLC-810A-SECRET-SERIAL" in raw_exif_jpeg

    result = make_yolo_result([(1, 0.91, [0.5, 0.5, 0.25, 0.3])])
    meta = {
        "event_type": "ANIMAL",
        "alarm_type": "ANIMAL",
        "fetch_ms": 42.1,
        "infer_ms": 18.7,
        "detections": [{"class": "prey", "confidence": 0.91}],
    }

    img_path_str, label_path_str = (
        evaluator._persist_clean_pair(  # pylint: disable=protected-access
            raw_exif_jpeg,
            result,
            prefix="prey",
            meta=meta,
        )
    )

    img_path = Path(img_path_str)
    label_path = Path(label_path_str)
    meta_path = labels_dir / f"{img_path.stem}.json"

    assert img_path.parent == images_dir
    assert label_path.parent == labels_dir
    assert img_path.is_file()
    assert label_path.is_file()
    assert meta_path.is_file()

    # 1. Saved JPEG must contain zero EXIF tags or camera serial strings
    saved_bytes = img_path.read_bytes()
    assert b"RLC-810A-SECRET-SERIAL" not in saved_bytes
    with Image.open(io.BytesIO(saved_bytes)) as saved_img:
        assert len(saved_img.getexif()) == 0

    # 2. YOLO label file remains pure 5-column numeric format
    assert label_path.read_text(encoding="utf-8").splitlines() == [
        "1 0.500000 0.500000 0.250000 0.300000"
    ]

    # 3. Sidecar JSON preserves webhook and inference telemetry
    loaded_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert loaded_meta["event_type"] == "ANIMAL"
    assert loaded_meta["infer_ms"] == 18.7

    # 4. Dataset listing surfaces JSON meta, while YOLO ZIP omits .json metadata
    listing = dataset.list_dataset_items(filter_mode="all")
    assert listing["total"] == 1
    assert listing["items"][0]["meta"]["alarm_type"] == "ANIMAL"

    zip_bytes = b"".join(dataset.iter_dataset_zip())
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert f"images/{img_path.name}" in names
        assert f"labels/{img_path.stem}.txt" in names
        assert not any(name.endswith(".json") for name in names)

    # 5. Deleting dataset item removes image, .txt label, and .json metadata together
    dataset.delete_dataset_item(img_path.name)
    assert not img_path.exists()
    assert not label_path.exists()
    assert not meta_path.exists()
