"""HTTP client for triggering the food dispenser on lockout expiration."""

import logging

# pylint: disable=import-error
import httpx

# pylint: enable=import-error
import config

logger = logging.getLogger(config.app_name)


async def trigger_dispenser(http_client: httpx.AsyncClient) -> None:
    """Send authenticated POST request to the oauth2-proxy protected /dispense API."""
    if (
        not config.dispenser_url
        or not config.dispenser_password
        or not config.dispenser_user
    ):
        logger.warning(
            "Dispenser skipped: DISPENSER_URL or DISPENSER_PASSWORD not set."
        )
        return

    payload = {
        "side": config.dispenser_side,
        "runsecs": config.dispenser_runsecs,
    }
    auth = httpx.BasicAuth(
        username=config.dispenser_user,
        password=config.dispenser_password,
    )

    try:
        resp = await http_client.post(
            config.dispenser_url,
            json=payload,
            auth=auth,
            timeout=10.0,
        )
        if resp.is_success:
            logger.info(
                "Dispenser triggered successfully (%d): %s",
                resp.status_code,
                resp.text,
            )
        else:
            logger.error(
                "Dispenser request rejected (%d): %s",
                resp.status_code,
                resp.text,
            )
    except httpx.RequestError as exc:
        logger.error("Network error calling dispenser API: %s", exc)
