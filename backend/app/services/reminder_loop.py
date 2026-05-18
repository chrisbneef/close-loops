"""Reminder tick — fires push notifications for tasks about to start.

Runs every `REMINDER_TICK_SECONDS` (default 60s). On each tick:
  1. Find calendar_blocks whose start is within [now, now + REMINDER_LEAD_MINUTES],
     whose task is still pending/scheduled (not started/done), where the owner
     has a push_token, and which we haven't pinged yet for THIS block instance.
  2. Send a push via the notifications service.
  3. Mark reminder_sent_at = now on the block so the next tick doesn't re-spam.

Re-pings handled implicitly: when the scheduler re-packs a task to a different
slot, persistence deletes the old calendar_block and inserts a new one with
reminder_sent_at = NULL, so the new time will get a fresh ping.

For v1 the loop sends one tier: a regular push. Section 8.1's "subtle pulse /
push / push-requiring-ack" escalation comes later (probably Phase 6d).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import CalendarBlock, Task, User
from app.services import notifications

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find_due_reminders(session: Session, *, now: datetime, lead_minutes: int) -> list:
    """Public for tests. Returns rows of (block, task, user) needing a ping."""
    cutoff = now + timedelta(minutes=lead_minutes)
    return list(
        session.execute(
            select(CalendarBlock, Task, User)
            .join(Task, Task.id == CalendarBlock.task_id)
            .join(User, User.id == Task.owner_id)
            .where(
                CalendarBlock.start >= now,
                CalendarBlock.start <= cutoff,
                CalendarBlock.reminder_sent_at.is_(None),
                Task.status.in_(("pending", "scheduled")),
                User.push_token.isnot(None),
            )
        ).all()
    )


def tick(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """One reminder pass. Returns {"sent": n, "failed": n, "skipped": n}."""
    now = now or datetime.now(timezone.utc)
    rows = find_due_reminders(session, now=now, lead_minutes=settings.reminder_lead_minutes)
    counts = {"sent": 0, "failed": 0, "skipped": 0}

    for block, task, user in rows:
        if not notifications.is_expo_push_token(user.push_token):
            counts["skipped"] += 1
            continue
        start_local = _as_utc(block.start).astimezone(
            __import__("zoneinfo").ZoneInfo(user.timezone or "UTC")
        )
        body = task.title
        title = f"Up next at {start_local.strftime('%-I:%M %p')}"
        try:
            notifications.send_push(
                user.push_token,
                title=title,
                body=body,
                data={"task_id": task.id, "block_id": block.id},
            )
            block.reminder_sent_at = now
            counts["sent"] += 1
        except notifications.PushError as e:
            logger.warning("reminder push failed task=%s: %s", task.id, e)
            counts["failed"] += 1

    session.commit()
    if counts["sent"] or counts["failed"]:
        logger.info("reminder_loop tick %s", counts)
    return counts


def _tick_job() -> None:
    session = SessionLocal()
    try:
        tick(session)
    except Exception:
        logger.exception("reminder_loop tick failed")
        session.rollback()
    finally:
        session.close()


def start() -> None:
    global _scheduler
    if not settings.enable_scheduler_loop:
        logger.info("reminder_loop disabled (settings.enable_scheduler_loop=False)")
        return
    if _scheduler is not None:
        logger.warning("reminder_loop already started")
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _tick_job, "interval", seconds=settings.reminder_tick_seconds, id="cadence_reminder",
    )
    _scheduler.start()
    logger.info("reminder_loop started: tick every %ss", settings.reminder_tick_seconds)


def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("reminder_loop stopped")
