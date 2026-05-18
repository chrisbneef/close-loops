"""Now-screen endpoints — what does the user do RIGHT NOW, and how do they
mark progress.

Three endpoints:
  GET  /next-action?owner_id=N    → the single next task + up_next dim list
  POST /tasks/{id}/start          → user hit Start; mark in_progress, stamp started_at
  POST /tasks/{id}/done           → user hit Done; mark done, log to execution_log,
                                    trigger a reschedule so the next task surfaces

The endpoints are deliberately minimal — the brain does the work; the mobile UI
just polls /next-action and presents the result.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CalendarBlock, ExecutionLog, Task
from app.schemas import NextActionResponse, TaskOut
from app.services import reschedule

logger = logging.getLogger(__name__)

router = APIRouter(tags=["now"])

# Tasks that are still "on the board" from the user's perspective. `decayed` is
# a soft-tombstone for tasks the user has implicitly abandoned; never surface them.
SURFACED_STATUSES = ("pending", "scheduled", "in_progress")


@router.get("/next-action", response_model=NextActionResponse)
def get_next_action(owner_id: int, session: Session = Depends(get_session)) -> NextActionResponse:
    """The user opens the app — what's the ONE thing to do? Returns the earliest-
    starting calendar_block for this owner whose task is still surfaceable.

    Returns an empty response (current=None) when the owner has no scheduled
    work — the mobile UI shows a calm "you're clear" state instead of an
    empty-list error."""
    rows = list(
        session.execute(
            select(CalendarBlock, Task)
            .join(Task, Task.id == CalendarBlock.task_id)
            .where(Task.owner_id == owner_id, Task.status.in_(SURFACED_STATUSES))
            .order_by(CalendarBlock.start.asc())
            .limit(3)
        ).all()
    )
    if not rows:
        return NextActionResponse()
    current_block, current_task = rows[0]
    return NextActionResponse(
        current=TaskOut.model_validate(current_task),
        current_start=current_block.start,
        current_end=current_block.end,
        why=_reason(current_block, current_task),
        up_next=[TaskOut.model_validate(t) for _, t in rows[1:]],
    )


def _reason(block: CalendarBlock, task: Task) -> str:
    """One-line human-readable rationale for why this task is the next action."""
    parts = [f"importance {task.importance}/10"]
    if task.deadline:
        parts.append(f"due {task.deadline.strftime('%b %-d')}")
    return f"{task.est_minutes} min · " + " · ".join(parts)


@router.post("/tasks/{task_id}/start", status_code=204)
def start_task(task_id: int, session: Session = Depends(get_session)) -> None:
    """User hit Start. Stamp started_at + flip status. Idempotent: re-calling on
    an already-in_progress task just refreshes started_at (so the user can
    resume after a break without losing the timer)."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")
    if task.status == "done":
        raise HTTPException(status_code=409, detail="task already done — cannot restart")
    task.status = "in_progress"
    task.started_at = datetime.now(timezone.utc)
    session.commit()
    logger.info("task start task_id=%s owner_id=%s", task_id, task.owner_id)


@router.post("/tasks/{task_id}/done", response_model=NextActionResponse)
def complete_task(task_id: int, session: Session = Depends(get_session)) -> NextActionResponse:
    """User hit Done. Stamp finished_at, log actual_minutes to execution_log
    (feeds the temporal correction factor), trigger a reschedule, and return
    the new /next-action so the UI can flip to the next thing without a
    second round trip."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")
    if task.status == "done":
        raise HTTPException(status_code=409, detail="task already done")

    now = datetime.now(timezone.utc)
    task.status = "done"
    task.finished_at = now

    # actual_minutes: prefer measured (started_at → now), fall back to est_minutes
    # if the user hit Done without Start (e.g. a quick fix they finished in seconds).
    if task.started_at:
        started = task.started_at if task.started_at.tzinfo else task.started_at.replace(tzinfo=timezone.utc)
        actual_minutes = max(1, int((now - started).total_seconds() // 60))
    else:
        actual_minutes = task.est_minutes
        task.started_at = now  # so execution_log's NOT NULL started_at is satisfied
    session.add(
        ExecutionLog(
            task_id=task.id,
            user_id=task.owner_id,
            estimated_minutes=task.est_minutes,
            actual_minutes=actual_minutes,
            started_at=task.started_at,
            finished_at=now,
        )
    )
    session.commit()
    logger.info(
        "task done task_id=%s owner_id=%s est=%s actual=%s",
        task_id, task.owner_id, task.est_minutes, actual_minutes,
    )

    # Re-pack so the next call to /next-action returns the new top of the queue.
    reschedule.request_reschedule_for_owner(
        task.owner_id, reason=f"task_done task_id={task_id}"
    )

    # Return what to do next in the same response.
    return get_next_action(task.owner_id, session)
