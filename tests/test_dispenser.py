# pylint: disable=import-error
"""Unit tests for dispenser.py lockout-expiration API trigger."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import config
import dispenser


@pytest.mark.asyncio
async def test_trigger_dispenser_skips_when_unconfigured(monkeypatch):
    """Verify trigger_dispenser returns early without HTTP calls when credentials are missing."""
    monkeypatch.setattr(config, "dispenser_url", "")
    monkeypatch.setattr(config, "dispenser_user", "admin")
    monkeypatch.setattr(config, "dispenser_password", "secret")

    mock_client = AsyncMock()
    await dispenser.trigger_dispenser(mock_client)
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_dispenser_sends_authenticated_post(monkeypatch):
    """Verify trigger_dispenser sends JSON payload and BasicAuth credentials."""
    monkeypatch.setattr(config, "dispenser_url", "https://feeder.local/dispense")
    monkeypatch.setattr(config, "dispenser_user", "feeder-user")
    monkeypatch.setattr(config, "dispenser_password", "feeder-pass")
    monkeypatch.setattr(config, "dispenser_side", "left")
    monkeypatch.setattr(config, "dispenser_runsecs", 3)

    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        is_success=True, status_code=200, text="ok"
    )

    await dispenser.trigger_dispenser(mock_client)

    mock_client.post.assert_awaited_once()
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://feeder.local/dispense"
    assert call_kwargs["json"] == {"side": "left", "runsecs": 3}
    assert isinstance(call_kwargs["auth"], httpx.BasicAuth)
    assert call_kwargs["timeout"] == 10.0


@pytest.mark.asyncio
async def test_trigger_dispenser_handles_http_and_network_errors(monkeypatch):
    """Verify non-2xx responses and httpx.RequestError are caught without raising."""
    monkeypatch.setattr(config, "dispenser_url", "https://feeder.local/dispense")
    monkeypatch.setattr(config, "dispenser_user", "feeder-user")
    monkeypatch.setattr(config, "dispenser_password", "feeder-pass")

    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        is_success=False, status_code=503, text="unavailable"
    )
    await dispenser.trigger_dispenser(mock_client)
    mock_client.post.assert_awaited_once()

    mock_client.post.reset_mock()
    mock_client.post.side_effect = httpx.ConnectError("connection refused")
    await dispenser.trigger_dispenser(mock_client)
    mock_client.post.assert_awaited_once()
