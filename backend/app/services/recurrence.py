"""Recurring-task spawning. When a task with `recurrence` set is marked done,
this module clones it as a fresh pending instance with the deadline advanced
by the recurrence interval and subtasks reset to uncompleted. Called from the
/done endpoint after the original task's completion has been logged.

`recurrence` values handled: 'daily' (+1 day), 'weekly' (+7 days),
'monthly' (+1 calendar month with month-end clamping so a Jan 31 deadline
becomes Feb 28/29 rather than crashing).
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task, TaskSubtask

logger = logging.getLogger(__name__)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add `months` calendar months to a tz-aware datetime, clamping to the
    last valid day of the target month (so Jan 31 + 1 month = Feb 28/29)."""
    new_month = dt.month + months
    new_year = dt.year + (new_month - 1) // 12
    new_month = ((new_month - 1) % 12) + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return dt.replace(year=new_year, month=new_month, day=min(dt.day, last_day))


def _next_deadline(deadline: Optional[datetime], recurrence: str) -> Optional[datetime]:
    if deadline is None:
        return None
    if recurrence == "daily":
        return deadline + timedelta(days=1)
    if recurrence == "weekly":
        return deadline + timedelta(days=7)
    if recurrence == "monthly":
        return _add_months(deadline, 1)
    return None


def spawn_next_if_recurring(session: Session, task: Task) -> Optional[Task]:
    """If `task` has a recurrence value, create + flush a fresh pending copy.
    Returns the new task (so the caller can trigger a reschedule) or None.

    The caller is responsible for the surrounding commit and reschedule.
    """
    if not task.recurrence:
        return None

    new_task = Task(
        title=task.title,
        description=task.description,
        project_id=task.project_id,
        owner_id=task.owner_id,
        delegator_id=task.delegator_id,
        est_minutes=task.est_minutes,
        importance=task.importance,
        deadline=_next_deadline(task.deadline, task.recurrence),
        recurrence=task.recurrence,
        status="pending",
    )
    session.add(new_task)
    session.flush()

    # Copy the SOP-style subtasks fresh (uncompleted) so the next occurrence
    # starts with a clean checklist. Subtasks aren't an ORM relationship — query
    # by task_id.
    original_subs = session.execute(
        select(TaskSubtask).where(TaskSubtask.task_id == task.id).order_by(TaskSubtask.position)
    ).scalars().all()
    for sub in original_subs:
        session.add(TaskSubtask(
            task_id=new_task.id,
            position=sub.position,
            title=sub.title,
            completed=False,
        ))

    logger.info(
        "recurring task spawned parent_id=%s new_id=%s recurrence=%s next_deadline=%s",
        task.id, new_task.id, task.recurrence, new_task.deadline,
    )
    return new_task
