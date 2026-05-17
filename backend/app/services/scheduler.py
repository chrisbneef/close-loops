"""Phase 3a orchestrator: pull tasks for an owner, compute priorities, get the
owner's free slots, run the greedy packer, return the proposed schedule.

Pure compute — does not persist to calendar_blocks. Phase 3b will add the
APScheduler tick + persistence + diff push to Google Calendar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CalendarBlock, Task, User
from app.services import momentum, priority
from app.services.calendar_provider import CalendarProvider, StubCalendarProvider
from app.services.packer import ScheduledBlock, TaskCandidate, pack

DEFAULT_HORIZON_DAYS = 14
ACTIVE_STATUSES = ("pending", "scheduled", "in_progress")


def _active_tasks(session: Session, owner_id: int) -> list[Task]:
    return list(
        session.execute(
            select(Task).where(Task.owner_id == owner_id, Task.status.in_(ACTIVE_STATUSES))
        ).scalars()
    )


def _existing_immutable_blocks(session: Session, task_ids: list[int]) -> dict[int, CalendarBlock]:
    if not task_ids:
        return {}
    rows = session.execute(
        select(CalendarBlock).where(CalendarBlock.task_id.in_(task_ids))
    ).scalars()
    return {b.task_id: b for b in rows}


def pack_for_owner(
    session: Session,
    owner_id: int,
    *,
    now: Optional[datetime] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    calendar: Optional[CalendarProvider] = None,
    daily_capacity_minutes: int = 360,
) -> tuple[list[ScheduledBlock], list[int]]:
    """Compute a proposed schedule for `owner_id`. Returns (blocks, unscheduled_task_ids).

    No DB writes happen here — callers can render/diff the proposal before
    committing it. Phase 3b will add the persistence step."""
    now = now or datetime.now(timezone.utc)
    owner = session.get(User, owner_id)
    if owner is None:
        raise ValueError(f"owner_id={owner_id} does not exist")

    tasks = _active_tasks(session, owner_id)
    if not tasks:
        return [], []

    task_ids = [t.id for t in tasks]
    momentum_map = momentum.momentum_by_task(session, task_ids)
    deps_map = momentum.dependencies_by_task(session, task_ids)
    immutable_blocks = _existing_immutable_blocks(
        session, [t.id for t in tasks if t.is_immutable]
    )

    candidates: list[TaskCandidate] = []
    for t in tasks:
        score = priority.compute_priority(
            t,
            now=now,
            momentum_weight=momentum_map.get(t.id, 0),
            owner_timezone=owner.timezone,
            owner_energy_curve=owner.energy_curve,
            alpha=settings.sched_alpha,
            beta=settings.sched_beta,
            gamma=settings.sched_gamma,
            delta=settings.sched_delta,
        )
        locked_start = None
        if t.is_immutable and t.id in immutable_blocks:
            locked_start = immutable_blocks[t.id].start
        candidates.append(
            TaskCandidate(
                task_id=t.id,
                title=t.title,
                est_minutes=t.est_minutes,
                priority=score,
                depends_on=deps_map.get(t.id, []),
                is_immutable=t.is_immutable,
                locked_start=locked_start,
            )
        )

    provider = calendar or StubCalendarProvider()
    slots = provider.free_slots(
        owner.timezone or "UTC",
        start=now,
        end=now + timedelta(days=horizon_days),
    )

    return pack(candidates, slots, daily_capacity_minutes=daily_capacity_minutes)
