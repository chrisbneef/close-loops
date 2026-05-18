"""Phase 6a: execution analytics. Answers the user's questions from the demo:
  - How many tasks did you complete on time?
  - How many ended up late?
  - On average, did you run over or under your estimates?

Reads from `execution_log` (joined to `tasks` for title/importance/deadline).
The Phase 7 daily briefing can layer Claude on top of this data to phrase the
same numbers conversationally — this endpoint just produces the structured stats.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ExecutionLog, Task, User
from app.schemas import ReportRow, WeeklyReport

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

DEFAULT_WINDOW_DAYS = 7


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite drops tzinfo on read; normalize before comparing."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/reports/weekly", response_model=WeeklyReport)
def get_weekly_report(
    owner_id: int,
    end_date: Optional[datetime] = Query(
        None,
        description="End of the report window (inclusive). Defaults to now. UTC.",
    ),
    window_days: int = Query(
        DEFAULT_WINDOW_DAYS,
        ge=1,
        le=90,
        description="Window size in days. Default 7 = a week.",
    ),
    session: Session = Depends(get_session),
) -> WeeklyReport:
    """Roll up everything in `execution_log` for `owner_id` within the window."""
    if session.get(User, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")

    end = _as_utc(end_date) or datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)

    rows = list(
        session.execute(
            select(ExecutionLog, Task)
            .join(Task, Task.id == ExecutionLog.task_id)
            .where(
                ExecutionLog.user_id == owner_id,
                ExecutionLog.finished_at >= start,
                ExecutionLog.finished_at <= end,
            )
            .order_by(ExecutionLog.finished_at.desc())
        ).all()
    )

    report_rows: list[ReportRow] = []
    ratios: list[float] = []
    by_importance: dict[int, dict[str, int]] = {}
    total_est = 0
    total_actual = 0
    on_time_count = 0
    late_count = 0
    no_deadline_count = 0

    for log, task in rows:
        deadline = _as_utc(task.deadline)
        finished = _as_utc(log.finished_at)
        on_time: Optional[bool]
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

        bucket = by_importance.setdefault(
            task.importance, {"completed": 0, "on_time": 0, "late": 0}
        )
        bucket["completed"] += 1
        if on_time is True:
            bucket["on_time"] += 1
        elif on_time is False:
            bucket["late"] += 1

        report_rows.append(
            ReportRow(
                task_id=task.id,
                title=task.title,
                importance=task.importance,
                estimated_minutes=log.estimated_minutes,
                actual_minutes=log.actual_minutes,
                deadline=deadline,
                scheduled_for=_as_utc(log.scheduled_for),
                started_at=_as_utc(log.started_at),
                finished_at=finished,
                on_time=on_time,
                over_estimate_ratio=round(ratio, 3),
            )
        )

    longest = None
    if report_rows:
        longest = max(
            report_rows,
            key=lambda r: r.actual_minutes - r.estimated_minutes,
        )

    return WeeklyReport(
        owner_id=owner_id,
        start_date=start,
        end_date=end,
        total_completed=len(report_rows),
        completed_on_time=on_time_count,
        completed_late=late_count,
        no_deadline=no_deadline_count,
        avg_actual_over_est=round(statistics.fmean(ratios), 3) if ratios else None,
        total_minutes_estimated=total_est,
        total_minutes_actual=total_actual,
        longest_overrun=longest,
        by_importance=dict(sorted(by_importance.items(), reverse=True)),  # 10 → 1
        rows=report_rows,
    )
