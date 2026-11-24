# pylint: disable=import-error
"""Unit tests for utils.py camera URL resolution and subnet validation."""

import ipaddress

import pytest
from fastapi import HTTPException

import config
import utils


def test_resolve_camera_url_ipv4():
    """Verify resolve_camera_url formats standard IPv4 address in camera_networks."""
    assert utils.resolve_camera_url("192.168.10.108") == "https://192.168.10.108"


def test_resolve_camera_url_allowed_ipv6(monkeypatch):
    """Verify resolve_camera_url formats IPv6 in brackets when allowed in camera_networks."""
    monkeypatch.setattr(
        config,
        "camera_networks",
        {ipaddress.ip_network("fd00::/8")},
    )
    assert utils.resolve_camera_url("fd00::1") == "https://[fd00::1]"


def test_resolve_camera_url_rejects_untrusted_and_public_ips():
    """Verify resolve_camera_url rejects public IPs not in camera_networks with 403."""
    with pytest.raises(HTTPException) as exc_v6:
        utils.resolve_camera_url("2001:db8::1")
    assert exc_v6.value.status_code == 403
    assert exc_v6.value.detail == "Client IP not in trusted camera subnet"

    with pytest.raises(HTTPException) as exc_v4:
        utils.resolve_camera_url("8.8.8.8")
    assert exc_v4.value.status_code == 403
    assert exc_v4.value.detail == "Client IP not in trusted camera subnet"


def test_resolve_camera_url_rejects_invalid_ip():
    """Verify resolve_camera_url raises 400 when client host is not a valid IP."""
    with pytest.raises(HTTPException) as exc_info:
        utils.resolve_camera_url("not-an-ip")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid client IP"


def test_resolve_camera_url_rejects_loopback_and_link_local():
    """Verify resolve_camera_url raises 403 on loopback or link-local addresses."""
    with pytest.raises(HTTPException) as exc_loopback:
        utils.resolve_camera_url("127.0.0.1")
    assert exc_loopback.value.status_code == 403

    with pytest.raises(HTTPException) as exc_linklocal:
        utils.resolve_camera_url("169.254.1.1")
    assert exc_linklocal.value.status_code == 403


def test_resolve_camera_url_fallback_when_none_or_unknown():
    """Verify resolve_camera_url falls back to config.camera_url when client host is missing."""
    expected = config.camera_url
    assert utils.resolve_camera_url(None) == expected
    assert utils.resolve_camera_url("unknown") == expected
    assert utils.resolve_camera_url("") == expected
