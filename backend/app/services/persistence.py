"""Diff a packer proposal against `calendar_blocks` and apply only the changes.

Idempotent: running it twice in a row with the same proposal produces no
writes on the second call. Locked blocks (set by a user manually pinning a
calendar entry) are never touched.

When a `CalendarProvider` is passed, the same diff is mirrored to the
upstream calendar (Google in Phase 4) — insert → create_event,
update → update_event, delete → delete_event. The provider's event_id is
stored on `calendar_blocks.gcal_event_id` so future updates/deletes can
find the upstream event again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CalendarBlock, Task
from app.services.calendar_provider import CalendarProvider
from app.services.packer import ScheduledBlock

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _times_match(existing_start, existing_end, proposed_start, proposed_end) -> bool:
    """SQLite returns naive datetimes from DateTime(timezone=True); normalize both
    to UTC tz-aware before comparing."""
    return (_as_utc(existing_start) == _as_utc(proposed_start)
            and _as_utc(existing_end) == _as_utc(proposed_end))


def apply_diff_for_owner(
    session: Session,
    owner_id: int,
    proposed: list[ScheduledBlock],
    *,
    provider: Optional[CalendarProvider] = None,
) -> dict[str, int]:
    """Apply the proposed schedule to `calendar_blocks` for one owner. If
    `provider` is given, mirror inserts/updates/deletes to the upstream calendar.

    Returns a counter: {"inserted": n, "updated": n, "deleted": n, "skipped_locked": n}.
    Caller commits.
    """
    existing_rows = (
        session.execute(
            select(CalendarBlock)
            .join(Task, Task.id == CalendarBlock.task_id)
            .where(Task.owner_id == owner_id)
        )
        .scalars()
        .all()
    )
    existing_by_task: dict[int, CalendarBlock] = {b.task_id: b for b in existing_rows}
    proposed_by_task: dict[int, ScheduledBlock] = {b.task_id: b for b in proposed}

    counts = {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 0}

    for block in proposed:
        current = existing_by_task.get(block.task_id)
        if current is None:
            event_id = None
            if provider is not None:
                try:
                    event_id = provider.create_event(
                        start=_as_utc(block.start),
                        end=_as_utc(block.end),
                        title=block.title,
                        task_id=block.task_id,
                    )
                except Exception:
                    logger.exception(
                        "create_event failed (task=%s); persisting locally without gcal_event_id",
                        block.task_id,
                    )
            session.add(
                CalendarBlock(
                    task_id=block.task_id,
                    start=_as_utc(block.start),
                    end=_as_utc(block.end),
                    gcal_event_id=event_id,
                    locked=False,
                )
            )
            counts["inserted"] += 1
            continue
        if current.locked:
            counts["skipped_locked"] += 1
            continue
        if _times_match(current.start, current.end, block.start, block.end):
            continue
        if provider is not None and current.gcal_event_id:
            try:
                provider.update_event(
                    event_id=current.gcal_event_id,
                    start=_as_utc(block.start),
                    end=_as_utc(block.end),
                    title=block.title,
                )
            except Exception:
                logger.exception(
                    "update_event failed (task=%s gcal=%s); DB still updated",
                    block.task_id, current.gcal_event_id,
                )
        current.start = _as_utc(block.start)
        current.end = _as_utc(block.end)
        counts["updated"] += 1

    # Delete blocks for tasks that fell out of the schedule. Never touch locked rows.
    for task_id, row in existing_by_task.items():
        if task_id in proposed_by_task:
            continue
        if row.locked:
            counts["skipped_locked"] += 1
            continue
        if provider is not None and row.gcal_event_id:
            try:
                provider.delete_event(event_id=row.gcal_event_id)
            except Exception:
                logger.exception(
                    "delete_event failed (task=%s gcal=%s); deleting DB row anyway",
                    task_id, row.gcal_event_id,
                )
        session.delete(row)
        counts["deleted"] += 1

    logger.info("calendar_blocks diff owner=%s %s", owner_id, counts)
    return counts


def changed(counts: dict[str, int]) -> bool:
    """True iff apply_diff_for_owner actually mutated state (insert/update/delete)."""
    return any(counts.get(k, 0) > 0 for k in ("inserted", "updated", "deleted"))
