# pylint: disable=import-error
"""Unit tests for vision.py image decoding, YOLO inference, and training pair persistence."""

from unittest.mock import MagicMock

import numpy as np

import vision
from tests.conftest import make_yolo_result


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
