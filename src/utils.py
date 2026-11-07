"""Shared HTTP request validation and camera network helper functions."""

import hmac
import ipaddress
from typing import Optional

# pylint: disable=import-error
from fastapi import HTTPException

# pylint: enable=import-error
import config


def resolve_camera_url(client_host: Optional[str]) -> str:
    """Build camera base URL from webhook client IP, falling back to config.camera_url."""
    default_url = config.camera_url
    if not client_host or client_host == "unknown":
        return default_url

    try:
        ip = ipaddress.ip_address(client_host)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client IP") from exc

    # Reject localhost, link-local (169.254.x.x), or non-LAN IPs
    if (
        ip.is_loopback
        or ip.is_link_local
        or not any(ip in net for net in config.camera_networks)
    ):
        raise HTTPException(
            status_code=403, detail="Client IP not in trusted camera subnet"
        )

    host = f"[{client_host}]" if ":" in client_host else client_host
    return (
        f"https://{host}"  # assume HTTPS by default (configure via Reolink web admin)
    )


def verify_secret(secret: Optional[str], x_webhook_secret: Optional[str]) -> None:
    """Validate shared secret from either query parameter or X-Webhook-Secret header."""
    provided_secret = secret or x_webhook_secret
    if (
        not config.webhook_secret
        or not provided_secret
        or not hmac.compare_digest(provided_secret, config.webhook_secret)
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
