"""Slack slash-command intake: `/loop <natural language goal>`.

Flow:
  1. Slack POSTs a form-encoded body to /slack/command.
  2. We verify the request signature (HMAC over the signing secret).
  3. We must answer within 3 seconds — so we return an immediate ephemeral
     ack and run the (slower) LLM decomposition in a background task.
  4. The background task resolves the requester (Slack user → Cadence user),
     runs the same /ingest pipeline (tasks + SOP subtasks + owner routing +
     deadline), and posts the result to the slash command's response_url.

Example: Michael types `/loop I need Chris to edit the launch video by Friday`.
The decomposer routes the work to Chris (partner), extracts Friday as the
deadline, and generates SOP subtasks for the video edit. Slack shows a
confirmation listing the created tasks.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_session
from app.models import User
from app.services import decomposition, slack

logger = logging.getLogger(__name__)

router = APIRouter(tags=["slack"])


def _resolve_requester(session: Session, slack_user_id: str) -> User | None:
    """Slack user → Cadence user. Falls back to the first cofounder so the
    command still works before slack_user_id mappings are populated."""
    user = None
    if slack_user_id:
        user = session.execute(
            select(User).where(User.slack_user_id == slack_user_id)
        ).scalar_one_or_none()
    if user is None:
        user = session.execute(
            select(User).where(User.role == "cofounder").order_by(User.id).limit(1)
        ).scalar_one_or_none()
    return user


def _process_goal(text: str, slack_user_id: str, response_url: str) -> None:
    """Background worker: decompose the goal and post the result to Slack.
    Runs on its own DB session (not the request session)."""
    session = SessionLocal()
    try:
        requester = _resolve_requester(session, slack_user_id)
        if requester is None:
            slack.post_to_response_url(
                response_url, "⚠️ No cofounder user exists — seed users first."
            )
            return
        resp = decomposition.ingest(session, raw_goal=text, owner_id=requester.id)

        # Group created tasks by owner for a readable confirmation.
        by_owner: dict[int, list] = {}
        for t in resp.tasks:
            by_owner.setdefault(t.owner_id, []).append(t)
        names = {u.id: u.name for u in session.execute(select(User)).scalars()}

        lines = [f"✓ *Broke that into {len(resp.tasks)} task(s):*"]
        for owner_id, tasks in by_owner.items():
            lines.append(f"\n_for {names.get(owner_id, 'someone')}:_")
            for t in tasks:
                sub = f"  ({len(t.subtasks)} steps)" if t.subtasks else ""
                lines.append(f"  • {t.title} — {t.est_minutes}m{sub}")
        if resp.tasks and resp.tasks[0].deadline:
            lines.append(f"\nDeadline: {resp.tasks[0].deadline.strftime('%a %b %-d')}")
        slack.post_to_response_url(response_url, "\n".join(lines))
        logger.info("slack /loop decomposed %s tasks for requester=%s", len(resp.tasks), requester.id)
    except Exception:
        logger.exception("slack /loop processing failed")
        slack.post_to_response_url(
            response_url, "⚠️ Couldn't process that one — check the brain logs."
        )
    finally:
        session.close()


@router.post("/slack/command")
async def slack_command(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()

    # Verify signature when a signing secret is configured. If it's not set
    # (dev without Slack wired up), we skip verification but log loudly.
    if settings.slack_signing_secret:
        ok = slack.verify_slack_signature(
            request_body=raw,
            timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
            signature=request.headers.get("X-Slack-Signature", ""),
        )
        if not ok:
            return {"response_type": "ephemeral", "text": "Signature verification failed."}
    else:
        logger.warning("SLACK_SIGNING_SECRET not set — skipping signature verification (dev only)")

    form = parse_qs(raw.decode())
    text = (form.get("text", [""])[0] or "").strip()
    slack_user_id = form.get("user_id", [""])[0]
    response_url = form.get("response_url", [""])[0]

    if not text:
        return {
            "response_type": "ephemeral",
            "text": "Usage: `/loop <what needs doing>` — e.g. `/loop I need Chris to edit the launch video by Friday`",
        }

    # Schedule the slow work; answer Slack immediately (3-second rule).
    background.add_task(_process_goal, text, slack_user_id, response_url)
    return {
        "response_type": "ephemeral",
        "text": f"Got it — breaking down: _{text}_ …\nI'll post the tasks here in a few seconds.",
    }
