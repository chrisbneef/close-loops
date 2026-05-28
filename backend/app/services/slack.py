"""Slack incoming-webhook helper. One function: post a text message.

Webhook URL lives in settings.slack_webhook_url. Calls become no-ops (log
warning) if the URL is unset, so dev work doesn't fail when the env isn't
fully populated.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SlackError(RuntimeError):
    """Webhook delivery failed (HTTP error or Slack rejected the payload)."""


def verify_slack_signature(
    *, request_body: bytes, timestamp: str, signature: str,
    signing_secret: str | None = None, max_age_seconds: int = 300,
) -> bool:
    """Verify a Slack request signature (slash commands, events).

    Slack signs: 'v0:{timestamp}:{raw_body}' with HMAC-SHA256 over the signing
    secret. We also reject requests older than 5 minutes (replay protection).
    """
    secret = signing_secret if signing_secret is not None else settings.slack_signing_secret
    if not secret:
        # No secret configured — can't verify. Caller decides whether to allow.
        return False
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            return False
    except (ValueError, TypeError):
        return False
    basestring = b"v0:" + timestamp.encode() + b":" + request_body
    expected = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def post_to_response_url(response_url: str, text: str, *, in_channel: bool = True) -> None:
    """Post a follow-up message to a slash command's response_url. Used after
    the immediate ack to deliver the (slower) decomposition result."""
    payload = {
        "response_type": "in_channel" if in_channel else "ephemeral",
        "text": text,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(response_url, json=payload).raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("slack response_url post failed: %s", e)


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
