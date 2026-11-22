# pylint: disable=too-many-instance-attributes
"""In-memory Prometheus metrics and telemetry aggregation for onlyCat(s)."""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# pylint: disable=import-error
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# pylint: enable=import-error

_MAX_RECENT_EVENTS = 250


@dataclass
class MetricsStore:
    """Thread-safe Prometheus registry and recent event ring buffers."""

    registry: CollectorRegistry = field(default_factory=CollectorRegistry)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _active_lock_start: float | None = None
    _active_lock_source: str = "unknown"
    recent_locks: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=_MAX_RECENT_EVENTS)
    )
    recent_detections: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=_MAX_RECENT_EVENTS)
    )
    hourly_locks: list[int] = field(default_factory=lambda: [0] * 24)
    hourly_detections: list[int] = field(default_factory=lambda: [0] * 24)
    started_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.door_locks_total = Counter(
            "onlycats_door_locks_total",
            "Total number of door lock activations.",
            labelnames=("source",),
            registry=self.registry,
        )
        self.door_unlocks_total = Counter(
            "onlycats_door_unlocks_total",
            "Total number of door unlock transitions.",
            labelnames=("source",),
            registry=self.registry,
        )
        self.door_lock_duration_seconds = Histogram(
            "onlycats_door_lock_duration_seconds",
            "Distribution of completed door lock durations in seconds.",
            buckets=(5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
            registry=self.registry,
        )
        self.door_locked = Gauge(
            "onlycats_door_locked",
            "Current physical lock state (1 = locked, 0 = unlocked).",
            registry=self.registry,
        )
        self.prey_detections_total = Counter(
            "onlycats_prey_detections_total",
            "Total number of prey detections or test triggers.",
            labelnames=("class_name", "event_type"),
            registry=self.registry,
        )
        self.prey_confidence = Histogram(
            "onlycats_prey_detection_confidence",
            "Distribution of YOLO detection confidence scores.",
            buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99),
            registry=self.registry,
        )
        self.camera_fetch_seconds = Histogram(
            "onlycats_camera_fetch_duration_seconds",
            "Reolink camera snapshot HTTP fetch latency in seconds.",
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self.registry,
        )
        self.yolo_infer_seconds = Histogram(
            "onlycats_yolo_inference_duration_seconds",
            "YOLO inference latency in seconds.",
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            registry=self.registry,
        )
        self.webhooks_total = Counter(
            "onlycats_webhooks_total",
            "Total incoming webhook requests by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.serial_reconnects_total = Counter(
            "onlycats_serial_reconnects_total",
            "Total ESP32 serial reconnection attempts.",
            registry=self.registry,
        )

    def record_lock(self, source: str = "prey_detection") -> None:
        """Record a door lock event and start timing its active duration."""
        now = time.time()
        hour = datetime.fromtimestamp(now, tz=timezone.utc).astimezone().hour
        self.door_locks_total.labels(source=source).inc()
        self.door_locked.set(1)
        with self._lock:
            self.hourly_locks[hour] += 1
            if self._active_lock_start is None:
                self._active_lock_start = now
                self._active_lock_source = source

    def record_unlock(self, source: str = "expiry") -> None:
        """Record a door unlock event and observe completed lock duration."""
        now = time.time()
        self.door_unlocks_total.labels(source=source).inc()
        self.door_locked.set(0)
        with self._lock:
            if self._active_lock_start is not None:
                duration = max(0.0, now - self._active_lock_start)
                self.door_lock_duration_seconds.observe(duration)
                self.recent_locks.append(
                    {
                        "timestamp": datetime.fromtimestamp(
                            self._active_lock_start, tz=timezone.utc
                        ).isoformat(),
                        "duration_sec": round(duration, 2),
                        "source": self._active_lock_source,
                        "unlock_source": source,
                    }
                )
                self._active_lock_start = None
                self._active_lock_source = "unknown"

    def record_prey_detection(
        self,
        detections: list[tuple[str, float]],
        is_test: bool = False,
    ) -> None:
        """Record prey detection count, class breakdown, confidence, and timestamp."""
        now = time.time()
        hour = datetime.fromtimestamp(now, tz=timezone.utc).astimezone().hour
        event_type = "TEST" if is_test else "ANIMAL"

        if detections:
            for cls_name, conf in detections:
                self.prey_detections_total.labels(
                    class_name=cls_name, event_type=event_type
                ).inc()
                self.prey_confidence.observe(conf)
        else:
            self.prey_detections_total.labels(
                class_name="test_trigger", event_type=event_type
            ).inc()

        with self._lock:
            self.hourly_detections[hour] += 1
            self.recent_detections.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        now, tz=timezone.utc
                    ).isoformat(),
                    "event_type": event_type,
                    "detections": [
                        {"class": c, "confidence": round(conf, 3)}
                        for c, conf in detections
                    ],
                }
            )

    def render_prometheus(self) -> tuple[bytes, str]:
        """Serialize metrics in standard Prometheus text exposition format."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

    def snapshot_json(self) -> dict[str, Any]:
        """Return structured runtime metrics for the Web UI telemetry drawer."""
        with self._lock:
            recent_locks = list(self.recent_locks)
            recent_detections = list(self.recent_detections)
            hourly_locks = list(self.hourly_locks)
            hourly_detections = list(self.hourly_detections)
            active_duration = (
                round(time.time() - self._active_lock_start, 1)
                if self._active_lock_start is not None
                else 0.0
            )

        # Bucket lock durations for UI histogram chart
        duration_buckets = [
            {"label": "<15s", "count": 0},
            {"label": "15-60s", "count": 0},
            {"label": "1-5m", "count": 0},
            {"label": "5-15m", "count": 0},
            {"label": ">15m", "count": 0},
        ]
        for item in recent_locks:
            dur = item["duration_sec"]
            if dur < 15:
                duration_buckets[0]["count"] += 1
            elif dur < 60:
                duration_buckets[1]["count"] += 1
            elif dur < 300:
                duration_buckets[2]["count"] += 1
            elif dur < 900:
                duration_buckets[3]["count"] += 1
            else:
                duration_buckets[4]["count"] += 1

        total_locks = sum(
            sample.value
            for metric in self.door_locks_total.collect()
            for sample in metric.samples
            if sample.name == "onlycats_door_locks_total"
        )
        total_unlocks = sum(
            sample.value
            for metric in self.door_unlocks_total.collect()
            for sample in metric.samples
            if sample.name == "onlycats_door_unlocks_total"
        )
        total_prey = sum(
            sample.value
            for metric in self.prey_detections_total.collect()
            for sample in metric.samples
            if sample.name == "onlycats_prey_detections_total"
        )

        return {
            "uptime_sec": int(time.time() - self.started_at),
            "totals": {
                "locks": int(total_locks),
                "unlocks": int(total_unlocks),
                "prey_detections": int(total_prey),
                "active_lock_sec": active_duration,
            },
            "hourly": {
                "locks": hourly_locks,
                "detections": hourly_detections,
            },
            "duration_buckets": duration_buckets,
            "recent_locks": recent_locks[-25:],
            "recent_detections": recent_detections[-25:],
        }


METRICS = MetricsStore()
