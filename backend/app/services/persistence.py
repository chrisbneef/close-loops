"""Diff a packer proposal against `calendar_blocks` and apply only the changes.

Idempotent: running it twice in a row with the same proposal produces no
writes on the second call. Locked blocks (set by a user manually pinning a
calendar entry) are never touched.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CalendarBlock, Task
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
    session: Session, owner_id: int, proposed: list[ScheduledBlock]
) -> dict[str, int]:
    """Apply the proposed schedule to `calendar_blocks` for one owner.

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

    counts = {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 0}
    proposed_task_ids: set[int] = set()

    for block in proposed:
        proposed_task_ids.add(block.task_id)
        current = existing_by_task.get(block.task_id)
        if current is None:
            session.add(
                CalendarBlock(
                    task_id=block.task_id,
                    start=_as_utc(block.start),
                    end=_as_utc(block.end),
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
        current.start = _as_utc(block.start)
        current.end = _as_utc(block.end)
        counts["updated"] += 1

    # Delete blocks for tasks that fell out of the schedule (capacity overflow,
    # dropped deps, completed task). Never touch locked rows.
    for task_id, row in existing_by_task.items():
        if task_id in proposed_task_ids:
            continue
        if row.locked:
            counts["skipped_locked"] += 1
            continue
        session.delete(row)
        counts["deleted"] += 1

    logger.info("calendar_blocks diff owner=%s %s", owner_id, counts)
    return counts


def changed(counts: dict[str, int]) -> bool:
    """True iff apply_diff_for_owner actually mutated state (insert/update/delete)."""
    return any(counts.get(k, 0) > 0 for k in ("inserted", "updated", "deleted"))
