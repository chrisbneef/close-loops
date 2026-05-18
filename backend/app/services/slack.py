"""Slack incoming-webhook helper. One function: post a text message.

Webhook URL lives in settings.slack_webhook_url. Calls become no-ops (log
warning) if the URL is unset, so dev work doesn't fail when the env isn't
fully populated.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SlackError(RuntimeError):
    """Webhook delivery failed (HTTP error or Slack rejected the payload)."""


def post_message(text: str, *, webhook_url: str | None = None, timeout_seconds: float = 10.0) -> bool:
    """Post a plain text message to Slack. Returns True on success, False if
    no webhook URL is configured (silent no-op). Raises SlackError on real failure.

    `webhook_url` overrides the global config — useful for per-channel routing later."""
    url = webhook_url or settings.slack_webhook_url
    if not url:
        logger.info("slack: no webhook URL configured; skipping post (text=%r)", text[:60])
        return False
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            r = client.post(url, json={"text": text})
            r.raise_for_status()
            # Slack returns "ok" as plain text body on success.
            if r.text.strip() != "ok":
                raise SlackError(f"Slack rejected payload: {r.text[:200]}")
    except httpx.HTTPError as e:
        raise SlackError(f"Slack HTTP failure: {e}") from e
    return True
