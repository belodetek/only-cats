"""Unit and API tests for dataset.py and /ui/dataset/* endpoints."""

import io
import zipfile

# pylint: disable=import-error
import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

# pylint: enable=import-error
import config
import dataset
import only_cats


def _write_sample_capture(
    images_dir, labels_dir, name: str, label_text: str | None = None
) -> None:
    """Create a synthetic 640x360 JPEG capture and optional YOLO label file."""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:, :] = (40, 120, 200)
    # pylint: disable=no-member
    ok, encoded = cv2.imencode(".jpg", img)
    # pylint: enable=no-member
    assert ok
    (images_dir / name).write_bytes(encoded.tobytes())
    if label_text is not None:
        (labels_dir / f"{name.rsplit('.', 1)[0]}.txt").write_text(
            label_text, encoding="utf-8"
        )


def test_list_filter_and_thumbnail_generation(tmp_data_dirs):
    """Verify newest-first listing, prey/empty filters, and downscaled thumbnails."""
    images_dir, labels_dir = tmp_data_dirs

    _write_sample_capture(
        images_dir, labels_dir, "other_cls.jpg", "1 0.5 0.5 0.4 0.4\n"
    )
    _write_sample_capture(
        images_dir,
        labels_dir,
        "prey_hit.jpg",
        "0 0.7 0.6 0.1 0.1\n1 0.4 0.5 0.3 0.4\n",
    )
    _write_sample_capture(images_dir, labels_dir, "unlabeled.jpg", None)

    all_res = dataset.list_dataset_items(filter_mode="all")
    assert all_res["counts"] == {"all": 3, "prey": 1, "empty": 1}
    assert all_res["total"] == 3

    prey_res = dataset.list_dataset_items(filter_mode="prey")
    assert prey_res["total"] == 1
    assert prey_res["items"][0]["filename"] == "prey_hit.jpg"
    assert prey_res["items"][0]["has_prey"] is True

    empty_res = dataset.list_dataset_items(filter_mode="empty")
    assert empty_res["total"] == 1
    assert empty_res["items"][0]["filename"] == "unlabeled.jpg"

    thumb_bytes = dataset.get_image_bytes("prey_hit.jpg", thumb=True)
    # pylint: disable=no-member
    decoded = cv2.imdecode(np.frombuffer(thumb_bytes, np.uint8), cv2.IMREAD_COLOR)
    # pylint: enable=no-member
    assert decoded is not None
    assert decoded.shape[1] == dataset.THUMB_MAX_WIDTH


def test_path_traversal_rejected(tmp_path, monkeypatch):
    """Verify directory traversal or non-image filenames raise HTTPException."""
    monkeypatch.setattr(config, "images_dir", str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        dataset.get_image_bytes("../secret.txt")
    assert exc_info.value.status_code == 400


def test_dataset_api_relabel_delete_and_zip_export(tmp_data_dirs):
    """Verify PUT labels, GET export.zip, and DELETE item endpoints end-to-end."""
    images_dir, labels_dir = tmp_data_dirs

    _write_sample_capture(images_dir, labels_dir, "frame_01.jpg", "1 0.5 0.5 0.4 0.4\n")
    _write_sample_capture(images_dir, labels_dir, "frame_02.jpg", None)

    client = TestClient(only_cats.app, headers={"X-Requested-With": "fetch"})

    # Relabel frame_01.jpg to class 0 (prey)
    put_resp = client.put(
        "/ui/dataset/labels/frame_01.jpg",
        json={"boxes": [{"cls": 0, "x": 0.25, "y": 0.35, "w": 0.2, "h": 0.2}]},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["boxes"][0]["cls"] == 0
    assert "0 0.250000 0.350000 0.200000 0.200000" in (
        labels_dir / "frame_01.txt"
    ).read_text(encoding="utf-8")

    # Export ZIP archive and verify single-class 0: prey data.yaml
    zip_resp = client.get("/ui/dataset/export.zip")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        names = set(zf.namelist())
        assert {
            "data.yaml",
            "images/frame_01.jpg",
            "labels/frame_01.txt",
            "images/frame_02.jpg",
            "labels/frame_02.txt",
        }.issubset(names)
        data_yaml = zf.read("data.yaml").decode("utf-8")
        assert "0: prey" in data_yaml
        assert "1:" not in data_yaml

    # Delete frame_01.jpg and verify both image and label are removed
    del_resp = client.delete("/ui/dataset/items/frame_01.jpg")
    assert del_resp.status_code == 200
    assert not (images_dir / "frame_01.jpg").exists()
    assert not (labels_dir / "frame_01.txt").exists()


def test_dataset_api_surfaces_metadata_and_strips_exif_on_serve(tmp_data_dirs):
    """Verify GET /ui/dataset/items returns JSON metadata and image endpoint strips EXIF."""
    images_dir, labels_dir = tmp_data_dirs

    # Write a legacy JPEG with EXIF directly into images_dir + a metadata JSON
    img = Image.new("RGB", (32, 32), color=(80, 140, 200))
    exif = Image.Exif()
    exif[272] = "LEGACY-CAM-SERIAL"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    (images_dir / "legacy_01.jpg").write_bytes(buf.getvalue())
    (labels_dir / "legacy_01.json").write_text(
        '{"event_type": "TEST", "infer_ms": 14.2}', encoding="utf-8"
    )

    client = TestClient(only_cats.app)

    items_resp = client.get("/ui/dataset/items?filter=all")
    assert items_resp.status_code == 200
    items = items_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["meta"] == {"event_type": "TEST", "infer_ms": 14.2}

    img_resp = client.get("/ui/dataset/image/legacy_01.jpg")
    assert img_resp.status_code == 200
    assert b"LEGACY-CAM-SERIAL" not in img_resp.content
    with Image.open(io.BytesIO(img_resp.content)) as served:
        assert len(served.getexif()) == 0


def test_dataset_api_purge_requires_delete_confirmation(tmp_data_dirs):
    """Verify DELETE /ui/dataset requires 'DELETE' confirmation and wipes images/labels/json."""
    images_dir, labels_dir = tmp_data_dirs

    _write_sample_capture(images_dir, labels_dir, "prey_01.jpg", "0 0.5 0.5 0.2 0.2\n")
    _write_sample_capture(images_dir, labels_dir, "train_02.jpg", "")
    (labels_dir / "prey_01.json").write_text(
        '{"event_type": "ANIMAL"}', encoding="utf-8"
    )
    (labels_dir / "train_02.json").write_text(
        '{"event_type": "TRAINING"}', encoding="utf-8"
    )

    client = TestClient(only_cats.app, headers={"X-Requested-With": "fetch"})

    # Reject wrong/lowercase confirmation string
    bad_resp = client.request("DELETE", "/ui/dataset", json={"confirm": "delete"})
    assert bad_resp.status_code == 400
    assert len(list(images_dir.glob("*.jpg"))) == 2

    # Accept exact "DELETE" confirmation and remove all images, labels, and JSON sidecars
    ok_resp = client.request("DELETE", "/ui/dataset", json={"confirm": "DELETE"})
    assert ok_resp.status_code == 200
    assert ok_resp.json() == {
        "purged": True,
        "deleted_images": 2,
        "deleted_labels": 2,
        "deleted_meta": 2,
    }
    assert not list(images_dir.iterdir())
    assert not list(labels_dir.iterdir())
