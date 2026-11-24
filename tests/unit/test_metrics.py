# pylint: disable=import-error
"""Unit and API tests for Prometheus exposition and runtime telemetry metrics."""

from fastapi.testclient import TestClient

import metrics
import only_cats
from tests.conftest import _patch_metrics_store


def test_metrics_store_records_locks_unlocks_and_duration_buckets():
    """Verify lock/unlock transitions update counters, gauges, and duration buckets."""
    store = metrics.MetricsStore()

    store.record_lock(source="prey_detection")
    snap_active = store.snapshot_json()
    assert snap_active["totals"]["locks"] == 1
    assert snap_active["totals"]["unlocks"] == 0
    assert snap_active["totals"]["active_lock_sec"] >= 0.0

    # Simulate a completed 45-second lock interval
    with store._lock:  # pylint: disable=protected-access
        store._active_lock_start -= 45.0  # pylint: disable=protected-access

    store.record_unlock(source="expiry")
    snap_done = store.snapshot_json()
    assert snap_done["totals"]["locks"] == 1
    assert snap_done["totals"]["unlocks"] == 1
    assert snap_done["totals"]["active_lock_sec"] == 0.0
    assert len(snap_done["recent_locks"]) == 1
    assert snap_done["recent_locks"][0]["source"] == "prey_detection"
    assert snap_done["recent_locks"][0]["unlock_source"] == "expiry"
    assert snap_done["recent_locks"][0]["duration_sec"] >= 45.0

    buckets = {b["label"]: b["count"] for b in snap_done["duration_buckets"]}
    assert buckets["15-60s"] == 1


def test_metrics_store_records_prey_detections_and_hourly_distribution():
    """Verify prey detections increment class counters, hourly bins, and recent feed."""
    store = metrics.MetricsStore()

    store.record_prey_detection([("prey", 0.92), ("mouse", 0.81)], is_test=False)
    store.record_prey_detection([], is_test=True)

    snap = store.snapshot_json()
    assert snap["totals"]["prey_detections"] == 3
    assert sum(snap["hourly"]["detections"]) == 2
    assert len(snap["recent_detections"]) == 2
    assert snap["recent_detections"][0]["event_type"] == "ANIMAL"
    assert snap["recent_detections"][0]["detections"] == [
        {"class": "prey", "confidence": 0.92},
        {"class": "mouse", "confidence": 0.81},
    ]
    assert snap["recent_detections"][1]["event_type"] == "TEST"


def test_prometheus_metrics_and_ui_metrics_endpoints(monkeypatch):
    """Verify GET /metrics exposes Prometheus text format and GET /ui/metrics returns JSON."""
    isolated_store = metrics.MetricsStore()
    isolated_store.record_lock(source="admin_ui")
    isolated_store.record_unlock(source="admin_ui")
    isolated_store.record_prey_detection([("prey", 0.89)], is_test=False)

    _patch_metrics_store(monkeypatch, isolated_store)

    client = TestClient(only_cats.app)

    prom_resp = client.get("/metrics")
    assert prom_resp.status_code == 200
    assert "text/plain" in prom_resp.headers["content-type"]
    body = prom_resp.text
    assert 'onlycats_door_locks_total{source="admin_ui"} 1.0' in body
    assert 'onlycats_door_unlocks_total{source="admin_ui"} 1.0' in body
    assert (
        'onlycats_prey_detections_total{class_name="prey",event_type="ANIMAL"} 1.0'
        in body
    )
    assert "onlycats_door_lock_duration_seconds_bucket" in body

    ui_resp = client.get("/ui/metrics")
    assert ui_resp.status_code == 200
    payload = ui_resp.json()
    assert payload["totals"]["locks"] == 1
    assert payload["totals"]["unlocks"] == 1
    assert payload["totals"]["prey_detections"] == 1
    assert len(payload["hourly"]["locks"]) == 24
    assert len(payload["hourly"]["detections"]) == 24
    assert len(payload["duration_buckets"]) == 5
