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
from app.models import CalendarBlock, ExecutionLog, Interruption, Task, TaskSubtask
from app.schemas import NextActionResponse, PauseRequest, SubtaskOut, TaskOut
from app.services import gamification, presence, reschedule

logger = logging.getLogger(__name__)

router = APIRouter(tags=["now"])

# Tasks that are still "on the board" from the user's perspective. `decayed` is
# a soft-tombstone for tasks the user has implicitly abandoned; never surface them.
# Paused tasks are still the user's "current" focus — they just stepped away.
SURFACED_STATUSES = ("pending", "scheduled", "in_progress", "paused")

# How many tasks /next-action returns (current + up_next). The widget shows a
# scrollable list, so a few more than the mobile screen's "one + 2 preview"
# makes manual adds visible without a full schedule view.
NEXT_ACTION_LIMIT = 6


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
            .limit(NEXT_ACTION_LIMIT)
        ).all()
    )
    if not rows:
        return NextActionResponse()
    current_block, current_task = rows[0]
    # Embed subtasks per task so the widget doesn't need N+1 fetches.
    task_ids = [t.id for _, t in rows]
    subtask_rows = list(session.execute(
        select(TaskSubtask).where(TaskSubtask.task_id.in_(task_ids)).order_by(TaskSubtask.position.asc())
    ).scalars())
    subs_by_task: dict[int, list[SubtaskOut]] = {}
    for sub in subtask_rows:
        subs_by_task.setdefault(sub.task_id, []).append(SubtaskOut.model_validate(sub))

    def _to_out(t: Task) -> TaskOut:
        out = TaskOut.model_validate(t)
        out.subtasks = subs_by_task.get(t.id, [])
        return out

    return NextActionResponse(
        current=_to_out(current_task),
        current_start=current_block.start,
        current_end=current_block.end,
        why=_reason(current_block, current_task),
        up_next=[_to_out(t) for _, t in rows[1:]],
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
    gamification.award_start(session, task.owner_id)
    # Body-doubling: tell the partner I'm heads-down on this one.
    presence.update_presence(
        session, task.owner_id, status="focusing", current_task_id=task.id,
    )
    session.commit()
    logger.info("task start task_id=%s owner_id=%s", task_id, task.owner_id)


@router.post("/tasks/{task_id}/pause", status_code=204)
def pause_task(
    task_id: int,
    body: PauseRequest,
    session: Session = Depends(get_session),
) -> None:
    """User hit Pause. Flip status to 'paused', open an Interruption row with
    `reason`, set presence to idle. Resume reverses each of these.

    Only valid when task is currently in_progress — pausing a pending task
    has no real meaning."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")
    if task.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail=f"can only pause a task that's in_progress (current status: {task.status})",
        )

    now = datetime.now(timezone.utc)
    task.status = "paused"
    session.add(Interruption(
        task_id=task.id, user_id=task.owner_id, paused_at=now, reason=body.reason,
    ))
    presence.update_presence(session, task.owner_id, status="idle", current_task_id=None)
    session.commit()
    logger.info("task paused task_id=%s reason=%r", task_id, body.reason)


@router.post("/tasks/{task_id}/resume", response_model=TaskOut)
def resume_task(task_id: int, session: Session = Depends(get_session)) -> TaskOut:
    """User hit Resume. Flip status back to in_progress, close the latest open
    Interruption row by stamping `resumed_at`, set presence back to focusing.
    Returns the task so the UI can immediately re-render."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")
    if task.status != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"can only resume a paused task (current status: {task.status})",
        )

    now = datetime.now(timezone.utc)
    task.status = "in_progress"
    open_interruption = session.execute(
        select(Interruption)
        .where(Interruption.task_id == task.id, Interruption.resumed_at.is_(None))
        .order_by(Interruption.paused_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if open_interruption is not None:
        open_interruption.resumed_at = now
    presence.update_presence(session, task.owner_id, status="focusing", current_task_id=task.id)
    session.commit()
    session.refresh(task)
    logger.info("task resumed task_id=%s", task_id)
    return TaskOut.model_validate(task)


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

    # Capture the brain's last scheduled start for this task BEFORE the reschedule
    # below wipes the calendar_block. Lets /reports/weekly compute drift between
    # scheduled vs actual completion time.
    block = session.execute(
        select(CalendarBlock).where(CalendarBlock.task_id == task.id).limit(1)
    ).scalar_one_or_none()
    scheduled_for = block.start if block else None

    session.add(
        ExecutionLog(
            task_id=task.id,
            user_id=task.owner_id,
            estimated_minutes=task.est_minutes,
            actual_minutes=actual_minutes,
            started_at=task.started_at,
            finished_at=now,
            scheduled_for=scheduled_for,
        )
    )
    gamification.award_done(session, task.owner_id, now=now)
    presence.update_presence(
        session, task.owner_id, status="idle", current_task_id=None,
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
