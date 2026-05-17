"""Greedy interval packer.

Algorithm (Section 5.2):
  1. Place immutable anchors first — they're fixed and never moved.
  2. Sort the remaining tasks by priority (already computed) descending.
  3. For each task, find the earliest feasible slot:
       - Comes after all prerequisite tasks have finished.
       - Has enough contiguous room for est_minutes.
       - The day's scheduled load (sum of est_minutes) is under the
         daily capacity cap.
  4. Place the task, fragment the slot's remaining time.
  5. Tasks that don't fit by the horizon end up in `unscheduled_task_ids`.

This module is pure compute — it does not write to the database. Phase 3b
persists the result to the `calendar_blocks` table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.services.calendar_provider import FreeSlot


@dataclass
class TaskCandidate:
    """Slim shape the packer consumes — keeps it independent of SQLAlchemy."""

    task_id: int
    title: str
    est_minutes: int
    priority: float
    depends_on: list[int] = field(default_factory=list)
    is_immutable: bool = False
    # For immutable tasks only — the locked start (already on the calendar):
    locked_start: datetime | None = None


@dataclass(frozen=True)
class ScheduledBlock:
    task_id: int
    title: str
    start: datetime
    end: datetime
    priority: float


def _fragment(slot: FreeSlot, used_start: datetime, used_end: datetime) -> list[FreeSlot]:
    """Return the leftover sub-slots after carving [used_start, used_end] out of `slot`."""
    out: list[FreeSlot] = []
    if used_start > slot.start:
        out.append(FreeSlot(start=slot.start, end=used_start))
    if used_end < slot.end:
        out.append(FreeSlot(start=used_end, end=slot.end))
    return out


def pack(
    tasks: list[TaskCandidate],
    free_slots: list[FreeSlot],
    *,
    daily_capacity_minutes: int = 360,  # 6h focused work / day by default
) -> tuple[list[ScheduledBlock], list[int]]:
    """Greedy DAG-aware packer. Returns (scheduled_blocks, unscheduled_task_ids)."""
    immutable = [t for t in tasks if t.is_immutable and t.locked_start is not None]
    mutable = [t for t in tasks if not (t.is_immutable and t.locked_start is not None)]

    # Sort free slots by start, copy so we can mutate.
    slots = sorted(free_slots, key=lambda s: s.start)

    scheduled: list[ScheduledBlock] = []
    minutes_used_per_day: dict[datetime.date, int] = {}

    # 1. Anchor immutable tasks first; subtract them from the slot pool.
    for t in immutable:
        start = t.locked_start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=t.est_minutes)
        scheduled.append(ScheduledBlock(t.task_id, t.title, start, end, t.priority))
        # Carve out from any slot that overlaps.
        new_slots: list[FreeSlot] = []
        for s in slots:
            if s.end <= start or s.start >= end:
                new_slots.append(s)
            else:
                new_slots.extend(_fragment(s, max(s.start, start), min(s.end, end)))
        slots = new_slots
        # Day capacity — immutable tasks count toward it.
        d = start.astimezone(timezone.utc).date()
        minutes_used_per_day[d] = minutes_used_per_day.get(d, 0) + t.est_minutes

    # 2. Topological-by-readiness, priority-tiebreaking. In each iteration:
    #    among tasks whose prereqs are all already scheduled, pick the highest
    #    priority and pack it. This way a higher-priority dependent doesn't
    #    "lose" its slot just because its prereqs weren't seen first.
    scheduled_by_id: dict[int, ScheduledBlock] = {b.task_id: b for b in scheduled}
    remaining: dict[int, TaskCandidate] = {t.task_id: t for t in mutable}
    # Pre-flag tasks whose dependencies aren't in the candidate set at all —
    # these can never become ready.
    candidate_ids = set(remaining)
    permanently_blocked = {
        tid for tid, t in remaining.items()
        if any(dep not in candidate_ids and dep not in scheduled_by_id for dep in t.depends_on)
    }
    unscheduled: list[int] = list(permanently_blocked)
    for tid in permanently_blocked:
        del remaining[tid]

    while remaining:
        ready = [
            t for t in remaining.values()
            if all(dep in scheduled_by_id for dep in t.depends_on)
        ]
        if not ready:
            # Remaining tasks form a cycle or only depend on each other. They
            # can never become ready. Cycle prevention upstream should make
            # this unreachable in practice — but don't loop forever.
            unscheduled.extend(remaining.keys())
            break
        ready.sort(key=lambda t: t.priority, reverse=True)
        t = ready[0]
        del remaining[t.task_id]

        # Earliest time the task can begin — after the latest prereq end.
        earliest_dep_end = max(
            (scheduled_by_id[dep].end for dep in t.depends_on),
            default=None,
        )

        duration = timedelta(minutes=t.est_minutes)
        placed = False
        for idx, slot in enumerate(slots):
            candidate_start = slot.start
            if earliest_dep_end is not None and earliest_dep_end > candidate_start:
                candidate_start = earliest_dep_end
            candidate_end = candidate_start + duration
            if candidate_end > slot.end:
                continue
            d = candidate_start.astimezone(timezone.utc).date()
            if minutes_used_per_day.get(d, 0) + t.est_minutes > daily_capacity_minutes:
                continue
            block = ScheduledBlock(t.task_id, t.title, candidate_start, candidate_end, t.priority)
            scheduled.append(block)
            scheduled_by_id[t.task_id] = block
            minutes_used_per_day[d] = minutes_used_per_day.get(d, 0) + t.est_minutes
            slots = (
                slots[:idx]
                + _fragment(slot, candidate_start, candidate_end)
                + slots[idx + 1 :]
            )
            placed = True
            break
        if not placed:
            unscheduled.append(t.task_id)

    scheduled.sort(key=lambda b: b.start)
    return scheduled, unscheduled
