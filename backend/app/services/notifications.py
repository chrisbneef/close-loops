"""Expo Push API wrapper.

Sends one push at a time to a single token. The Expo service handles iOS/
Android delivery, retries, and APNs/FCM cert management — we just POST a small
JSON body and let them deal with the rest.

Docs: https://docs.expo.dev/push-notifications/sending-notifications/

The `EXPO_ACCESS_TOKEN` is only required if the recipient project has access
tokens enforced in their Expo dashboard. For dev / Expo Go, it's optional.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_TOKEN_PREFIX = "ExponentPushToken["  # all valid Expo tokens start with this


class PushError(RuntimeError):
    """Raised when Expo refuses the push (bad token, malformed payload, etc).

    Callers usually want to swallow this so one bad token doesn't take down the
    whole reminder tick — log it and move on."""


def is_expo_push_token(token: Optional[str]) -> bool:
    return bool(token and token.startswith(EXPO_PUSH_TOKEN_PREFIX))


def send_push(
    token: str,
    *,
    title: str,
    body: str,
    data: Optional[dict] = None,
    timeout_seconds: float = 10.0,
) -> dict:
    """POST one push to the Expo service. Returns the response body."""
    if not is_expo_push_token(token):
        raise PushError(f"Not a valid Expo push token: {token!r}")
    payload = {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "data": data or {},
        "priority": "high",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            r = client.post(EXPO_PUSH_URL, json=payload, headers=headers)
            r.raise_for_status()
            response = r.json()
    except httpx.HTTPError as e:
        raise PushError(f"Expo push HTTP failure: {e}") from e

    # Expo returns {"data": {"status": "ok"|"error", ...}}
    data_block = response.get("data") or {}
    if isinstance(data_block, dict) and data_block.get("status") == "error":
        raise PushError(
            f"Expo push rejected: {data_block.get('message')} (code={data_block.get('details', {}).get('error')})"
        )
    return response
