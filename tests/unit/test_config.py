# pylint: disable=import-error
"""Unit tests for config.py environment parsing."""

import importlib
import ipaddress

import pytest

import config


@pytest.fixture(autouse=True)
def _restore_config_module_after_reload(monkeypatch):
    """Reload config cleanly after each test so monkeypatched env vars do not persist."""
    yield
    monkeypatch.undo()
    importlib.reload(config)


def test_config_parses_target_classes_and_recipients(monkeypatch):
    """Verify comma-separated TARGET_CLASSES and SIGNAL_RECIPIENTS parse cleanly."""
    monkeypatch.setenv("TARGET_CLASSES", "prey, mouse , bird ")
    monkeypatch.setenv("SIGNAL_RECIPIENTS", " +12505550100 , group.xyz= ")
    importlib.reload(config)

    assert config.target_classes == {"prey", "mouse", "bird"}
    assert config.signal_recipients == ["+12505550100", "group.xyz="]


def test_config_parses_camera_networks(monkeypatch):
    """Verify comma-separated CAMERA_NETWORKS parse into ip_network objects."""
    monkeypatch.setenv("CAMERA_NETWORKS", "10.0.0.0/8, 192.168.1.0/24")
    importlib.reload(config)

    assert config.camera_networks == {
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("192.168.1.0/24"),
    }


def test_config_parses_webhook_secret_and_in_training(monkeypatch):
    """Verify WEBHOOK_SECRET and boolean IN_TRAINING flags load from environment."""
    monkeypatch.setenv("WEBHOOK_SECRET", "custom-secret")
    monkeypatch.setenv("IN_TRAINING", "true")
    importlib.reload(config)

    assert config.webhook_secret == "custom-secret"
    assert config.in_training is True
