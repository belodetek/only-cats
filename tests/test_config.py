"""Unit tests for config.py environment parsing."""

import importlib

import config


def test_config_parses_target_classes_and_recipients(monkeypatch):
    """Verify comma-separated TARGET_CLASSES and SIGNAL_RECIPIENTS parse cleanly."""
    monkeypatch.setenv("TARGET_CLASSES", "prey, mouse , bird ")
    monkeypatch.setenv("SIGNAL_RECIPIENTS", " +12505550100 , group.xyz= ")
    importlib.reload(config)

    assert config.target_classes == {"prey", "mouse", "bird"}
    assert config.signal_recipients == ["+12505550100", "group.xyz="]
