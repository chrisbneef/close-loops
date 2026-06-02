"""Period reporting (daily / weekly). Gathers, for one owner in a time window:
  - completed work (from execution_log) + the existing on-time / over-estimate stats
  - what DIDN'T get done (scheduled-in-window-but-unfinished, plus overdue)
  - decayed tasks (empty until decay-marking ships)
  - a pause/interruption rollup → "biggest distraction"

Returns a PeriodReport with memo=None; the caller fills in the narrative memo
(see report_memo.py) so this stays pure/testable without an LLM.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CalendarBlock, ExecutionLog, Interruption, Task
from app.schemas import OpenTaskRow, PeriodReport, ReportRow

# Statuses that mean "still open" — not finished, not tombstoned.
_OPEN_STATUSES = ("whiteboard", "pending", "scheduled", "in_progress", "paused")


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_report(
    session: Session,
    owner_id: int,
    *,
    granularity: str,
    start: datetime,
    end: datetime,
) -> PeriodReport:
    start = _as_utc(start)
    end = _as_utc(end)

    completed = _completed(session, owner_id, start, end)
    incomplete = _incomplete(session, owner_id, start, end)
    decayed = _decayed(session, owner_id, start, end)
    pauses = _pauses(session, owner_id, start, end)

    return PeriodReport(
        owner_id=owner_id,
        granularity=granularity,
        start_date=start,
        end_date=end,
        **completed,
        incomplete=incomplete,
        decayed=decayed,
        **pauses,
        memo=None,
    )


def _completed(session: Session, owner_id: int, start: datetime, end: datetime) -> dict:
    rows = list(session.execute(
        select(ExecutionLog, Task)
        .join(Task, Task.id == ExecutionLog.task_id)
        .where(
            ExecutionLog.user_id == owner_id,
            ExecutionLog.finished_at >= start,
            ExecutionLog.finished_at <= end,
        )
        .order_by(ExecutionLog.finished_at.desc())
    ).all())

    report_rows: list[ReportRow] = []
    ratios: list[float] = []
    by_importance: dict[int, dict[str, int]] = {}
    total_est = total_actual = on_time_count = late_count = no_deadline_count = 0

    for log, task in rows:
        deadline = _as_utc(task.deadline)
        finished = _as_utc(log.finished_at)
        if deadline is None:
            on_time = None
            no_deadline_count += 1
        elif finished <= deadline:
            on_time = True
            on_time_count += 1
        else:
            on_time = False
            late_count += 1

        ratio = log.actual_minutes / max(log.estimated_minutes, 1)
        ratios.append(ratio)
        total_est += log.estimated_minutes
        total_actual += log.actual_minutes

        bucket = by_importance.setdefault(task.importance, {"completed": 0, "on_time": 0, "late": 0})
        bucket["completed"] += 1
        if on_time is True:
            bucket["on_time"] += 1
        elif on_time is False:
            bucket["late"] += 1

        report_rows.append(ReportRow(
            task_id=task.id, title=task.title, importance=task.importance,
            estimated_minutes=log.estimated_minutes, actual_minutes=log.actual_minutes,
            deadline=deadline, scheduled_for=_as_utc(log.scheduled_for),
            started_at=_as_utc(log.started_at), finished_at=finished,
            on_time=on_time, over_estimate_ratio=round(ratio, 3),
            completion_notes=log.completion_notes,
        ))

    longest = max(report_rows, key=lambda r: r.actual_minutes - r.estimated_minutes) if report_rows else None

    return {
        "total_completed": len(report_rows),
        "completed_on_time": on_time_count,
        "completed_late": late_count,
        "no_deadline": no_deadline_count,
        "avg_actual_over_est": round(statistics.fmean(ratios), 3) if ratios else None,
        "total_minutes_estimated": total_est,
        "total_minutes_actual": total_actual,
        "longest_overrun": longest,
        "by_importance": dict(sorted(by_importance.items(), reverse=True)),
        "rows": report_rows,
    }


def _incomplete(session: Session, owner_id: int, start: datetime, end: datetime) -> list[OpenTaskRow]:
    """Open tasks that were scheduled within the window (block start in [start,end])
    OR are overdue as of `end`. These are the 'didn't get done' items."""
    scheduled_ids = set(session.execute(
        select(CalendarBlock.task_id)
        .join(Task, Task.id == CalendarBlock.task_id)
        .where(
            Task.owner_id == owner_id,
            Task.status.in_(_OPEN_STATUSES),
            CalendarBlock.start >= start,
            CalendarBlock.start <= end,
        )
    ).scalars())

    overdue_ids = set(session.execute(
        select(Task.id).where(
            Task.owner_id == owner_id,
            Task.status.in_(_OPEN_STATUSES),
            Task.deadline.is_not(None),
            Task.deadline <= end,
        )
    ).scalars())

    task_ids = scheduled_ids | overdue_ids
    if not task_ids:
        return []

    tasks = list(session.execute(select(Task).where(Task.id.in_(task_ids))).scalars())
    out: list[OpenTaskRow] = []
    for t in tasks:
        deadline = _as_utc(t.deadline)
        created = _as_utc(t.created_at)
        out.append(OpenTaskRow(
            task_id=t.id, title=t.title, importance=t.importance, status=t.status,
            deadline=deadline,
            overdue=bool(deadline and deadline <= end),
            age_days=(end - created).days if created else None,
        ))
    # Overdue first, then by importance.
    out.sort(key=lambda r: (not r.overdue, -r.importance))
    return out


def _decayed(session: Session, owner_id: int, start: datetime, end: datetime) -> list[OpenTaskRow]:
    tasks = list(session.execute(
        select(Task).where(
            Task.owner_id == owner_id,
            Task.status == "decayed",
            Task.updated_at >= start,
            Task.updated_at <= end,
        )
    ).scalars())
    return [
        OpenTaskRow(
            task_id=t.id, title=t.title, importance=t.importance, status=t.status,
            deadline=_as_utc(t.deadline), overdue=False,
            age_days=(end - _as_utc(t.created_at)).days if t.created_at else None,
        )
        for t in tasks
    ]


def _pauses(session: Session, owner_id: int, start: datetime, end: datetime) -> dict:
    rows = list(session.execute(
        select(Interruption).where(
            Interruption.user_id == owner_id,
            Interruption.paused_at >= start,
            Interruption.paused_at <= end,
        )
    ).scalars())

    reasons: dict[str, int] = {}
    total_minutes = 0
    for intr in rows:
        reason = (intr.reason or "").strip() or "(no reason given)"
        reasons[reason] = reasons.get(reason, 0) + 1
        if intr.resumed_at is not None:
            paused = _as_utc(intr.paused_at)
            resumed = _as_utc(intr.resumed_at)
            total_minutes += max(0, int((resumed - paused).total_seconds() // 60))

    biggest = max(reasons, key=reasons.get) if reasons else None
    return {
        "total_pauses": len(rows),
        "total_pause_minutes": total_minutes,
        "pause_reasons": dict(sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)),
        "biggest_distraction": biggest,
    }
