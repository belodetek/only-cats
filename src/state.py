"""Shared runtime dependency container for the FastAPI application."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

# pylint: disable=import-error
import httpx
from ultralytics import YOLO

# pylint: enable=import-error
from esp32 import ESP32SerialController
from flasher import AppDescriptor


# pylint: disable=too-few-public-methods,too-many-instance-attributes
@dataclass
class AppState:
    """Encapsulates shared runtime dependencies without requiring global variables."""

    controller: Optional[ESP32SerialController] = None
    dispenser_client: Optional[httpx.AsyncClient] = None
    esp32_chip_desc: Optional[AppDescriptor] = None
    esp32_local_desc: Optional[AppDescriptor] = None
    eval_semaphore: Optional[asyncio.Semaphore] = None
    http_client: Optional[httpx.AsyncClient] = None
    model_metadata: dict[str, Any] = field(default_factory=dict)
    model: Optional[YOLO] = None
    pending_evaluations: int = 0
    prelock_cooldown_until: float = 0.0
