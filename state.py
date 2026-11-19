"""Shared runtime dependency container for the FastAPI application."""

from dataclasses import dataclass
from typing import Optional

# pylint: disable=import-error
import httpx
from ultralytics import YOLO

# pylint: enable=import-error
from esp32 import ESP32SerialController


# pylint: disable=too-few-public-methods
@dataclass
class AppState:
    """Encapsulates shared runtime dependencies without requiring global variables."""

    controller: Optional[ESP32SerialController] = None
    model: Optional[YOLO] = None
    http_client: Optional[httpx.AsyncClient] = None
