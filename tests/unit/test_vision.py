# pylint: disable=too-many-locals
"""Unit tests for vision.py inference, EXIF metadata stripping,
and JSON metadata persistence."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# pylint: disable=import-error
import numpy as np
import pytest
from PIL import Image

# pylint: enable=import-error
import config
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


def _solid_jpeg_bytes(width: int = 1000, height: int = 1000) -> bytes:
    """Encode a solid RGB JPEG of exact dimensions for cascade geometry tests."""
    img = Image.new("RGB", (width, height), color=(90, 110, 130))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _tensor_mock(values: list[Any]) -> MagicMock:
    """Return a mock tensor exposing .cpu().numpy() -> np.ndarray."""
    tensor = MagicMock()
    tensor.cpu.return_value.numpy.return_value = np.array(values, dtype=np.float32)
    return tensor


def _make_pixel_result(
    boxes_xyxy: list[tuple[int, float, tuple[float, float, float, float]]],
    orig_shape: tuple[int, int] = (1000, 1000),
) -> MagicMock:
    """Build a mock Ultralytics Results object with pixel xyxy boxes."""
    res = MagicMock()
    res.orig_shape = orig_shape
    if not boxes_xyxy:
        res.boxes = []
        return res

    boxes = MagicMock()
    boxes.__len__.return_value = len(boxes_xyxy)
    boxes.cls = _tensor_mock([b[0] for b in boxes_xyxy])
    boxes.conf = _tensor_mock([b[1] for b in boxes_xyxy])
    boxes.xyxy = _tensor_mock([b[2] for b in boxes_xyxy])
    res.boxes = boxes
    return res


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


def test_cascade_inference_remaps_crop_boxes_to_full_frame():
    """Verify full-frame pass + Stage 1 padded cat crop pass remap boxes to [0, 1]."""
    img_array = np.frombuffer(_solid_jpeg_bytes(1000, 1000), dtype=np.uint8)

    # Stage 1 detects a cat at [200, 100, 600, 500] (400x400); with pad_ratio=0.20,
    # padded crop is [120:680, 20:580] (560x560).
    cat_model = MagicMock()
    cat_model.predict.return_value = [
        _make_pixel_result([(15, 0.88, (200.0, 100.0, 600.0, 500.0))])
    ]

    # Stage 2 runs first on the full 1000x1000 frame (misses small prey: []),
    # then on the 560x560 crop where it detects prey at crop-local [100, 100, 200, 200]
    # -> global [220, 120, 320, 220] -> normalized center (0.27, 0.17), size (0.10, 0.10).
    prey_model = MagicMock()
    prey_model.predict.side_effect = [
        [_make_pixel_result([], orig_shape=(1000, 1000))],
        [
            _make_pixel_result(
                [(0, 0.94, (100.0, 100.0, 200.0, 200.0))], orig_shape=(560, 560)
            )
        ],
    ]

    cascade = vision.CascadeConfig(
        cat_model=cat_model,
        cat_conf=0.20,
        pad_ratio=0.20,
    )
    img, detections = vision.run_cascade_inference(
        prey_model,
        img_array,
        conf=0.5,
        cascade=cascade,
    )

    assert img is not None
    cat_model.predict.assert_called_once()
    assert cat_model.predict.call_args[1]["classes"] == vision.COCO_ANIMAL_CLASSES
    assert cat_model.predict.call_args[1]["conf"] == 0.20

    assert prey_model.predict.call_count == 2
    full_arg = prey_model.predict.call_args_list[0][1]["source"]
    crop_arg = prey_model.predict.call_args_list[1][1]["source"]
    assert full_arg.shape[:2] == (1000, 1000)
    assert crop_arg.shape[:2] == (560, 560)

    assert len(detections) == 1
    det = detections[0]
    assert det.cls == 0
    assert det.confidence == pytest.approx(0.94)
    assert det.x == pytest.approx(0.27)
    assert det.y == pytest.approx(0.17)
    assert det.w == pytest.approx(0.10)
    assert det.h == pytest.approx(0.10)


def test_cascade_inference_falls_back_to_full_frame_when_no_cat():
    """Verify Stage 2 runs on the full frame when Stage 1 detects zero cats/dogs."""
    img_array = np.frombuffer(_solid_jpeg_bytes(800, 600), dtype=np.uint8)

    cat_model = MagicMock()
    cat_model.predict.return_value = [_make_pixel_result([], orig_shape=(600, 800))]

    prey_model = MagicMock()
    prey_model.predict.return_value = [
        _make_pixel_result(
            [(0, 0.87, (320.0, 240.0, 480.0, 360.0))], orig_shape=(600, 800)
        )
    ]

    cascade = vision.CascadeConfig(cat_model=cat_model)
    img, detections = vision.run_cascade_inference(
        prey_model, img_array, conf=0.5, cascade=cascade
    )

    assert img is not None
    prey_model.predict.assert_called_once()
    full_arg = prey_model.predict.call_args[1]["source"]
    assert full_arg.shape[:2] == (600, 800)

    assert len(detections) == 1
    assert detections[0].x == pytest.approx(0.5)
    assert detections[0].y == pytest.approx(0.5)
    assert detections[0].w == pytest.approx(0.2)
    assert detections[0].h == pytest.approx(0.2)


def test_cascade_inference_deduplicates_overlapping_cat_crops():
    """Verify overlapping prey boxes from two adjacent cat crops collapse to highest score."""
    img_array = np.frombuffer(_solid_jpeg_bytes(1000, 1000), dtype=np.uint8)

    # Two overlapping Stage 1 detections produce two crops covering the same prey
    cat_model = MagicMock()
    cat_model.predict.return_value = [
        _make_pixel_result(
            [
                (15, 0.90, (200.0, 200.0, 500.0, 500.0)),
                (16, 0.75, (220.0, 200.0, 520.0, 500.0)),
            ]
        )
    ]

    prey_model = MagicMock()
    prey_model.predict.side_effect = [
        [_make_pixel_result([], orig_shape=(1000, 1000))],
        [
            _make_pixel_result(
                [(0, 0.82, (150.0, 150.0, 250.0, 250.0))], orig_shape=(420, 420)
            )
        ],
        [
            _make_pixel_result(
                [(0, 0.95, (130.0, 150.0, 230.0, 250.0))], orig_shape=(420, 420)
            )
        ],
    ]

    cascade = vision.CascadeConfig(cat_model=cat_model, pad_ratio=0.20)
    _, detections = vision.run_cascade_inference(
        prey_model, img_array, conf=0.5, cascade=cascade
    )

    assert prey_model.predict.call_count == 3
    assert len(detections) == 1
    assert detections[0].confidence == pytest.approx(0.95)


def test_persist_clean_pair_strips_exif_writes_metadata_and_keeps_yolo_zip_clean(
    tmp_data_dirs, monkeypatch
):
    """Verify EXIF is stripped from persisted JPEGs and webhook meta lives only in .json."""
    monkeypatch.setattr(config, "min_blur_variance", 0.0)
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
