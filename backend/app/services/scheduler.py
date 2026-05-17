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
from app.services import momentum, priority, persistence
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


def _cross_owner_anchor_blocks(
    session: Session, owner_id: int, deps_map: dict[int, list[int]], candidate_ids: set[int]
) -> list[ScheduledBlock]:
    """For each candidate's deps that point to a task NOT in this owner's
    candidate set (i.e., delegated to / from another owner), load the persisted
    `calendar_blocks` row and wrap as a ScheduledBlock so the packer can satisfy
    the dep check without re-scheduling that other-owner task."""
    external_task_ids: set[int] = set()
    for deps in deps_map.values():
        for dep_id in deps:
            if dep_id not in candidate_ids:
                external_task_ids.add(dep_id)
    if not external_task_ids:
        return []

    rows = (
        session.execute(
            select(CalendarBlock, Task)
            .join(Task, Task.id == CalendarBlock.task_id)
            .where(CalendarBlock.task_id.in_(external_task_ids))
        )
        .all()
    )
    anchors: list[ScheduledBlock] = []
    for block, task in rows:
        anchors.append(
            ScheduledBlock(
                task_id=task.id,
                title=task.title,
                # SQLite drops tzinfo on DateTime(timezone=True) reads; tz-aware
                # UTC is what the packer compares against.
                start=_to_utc(block.start),
                end=_to_utc(block.end),
                priority=0.0,  # not used for anchors
            )
        )
    return anchors


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
            locked_start = _to_utc(immutable_blocks[t.id].start)
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

    anchors = _cross_owner_anchor_blocks(session, owner_id, deps_map, set(task_ids))

    return pack(
        candidates,
        slots,
        daily_capacity_minutes=daily_capacity_minutes,
        existing_anchors=anchors,
    )


def apply_schedule_for_owner(
    session: Session,
    owner_id: int,
    *,
    now: Optional[datetime] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    calendar: Optional[CalendarProvider] = None,
    daily_capacity_minutes: int = 360,
) -> tuple[list[ScheduledBlock], list[int], dict[str, int]]:
    """Pack + persist for one owner. Returns (blocks, unscheduled_ids, diff_counts).

    Caller commits."""
    blocks, unscheduled = pack_for_owner(
        session,
        owner_id,
        now=now,
        horizon_days=horizon_days,
        calendar=calendar,
        daily_capacity_minutes=daily_capacity_minutes,
    )
    counts = persistence.apply_diff_for_owner(session, owner_id, blocks)
    return blocks, unscheduled, counts
