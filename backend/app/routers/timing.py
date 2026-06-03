"""Edit Time endpoints — let the user fix the recorded time on a task or its
pauses after the fact, for when they forgot to hit Start / Done / Resume.

Three routes:

  GET   /tasks/{id}/timing       → execution_log (if completed) + all pauses
  PATCH /execution-log/{id}      → fix start/end/total for a completed run
  PATCH /interruptions/{id}      → fix paused_at/resumed_at/reason for a pause

When start/end change on an execution_log row, actual_minutes is recomputed
from the new bounds unless the caller explicitly sets it themselves — the
field is the source of truth for the weekly report, so we keep it consistent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ExecutionLog, Interruption, Task
from app.schemas import (
    ExecutionLogOut, ExecutionLogUpdate, InterruptionOut, InterruptionUpdate,
    TimingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timing"])


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/tasks/{task_id}/timing", response_model=TimingResponse)
def get_task_timing(task_id: int, session: Session = Depends(get_session)) -> TimingResponse:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")

    log = session.execute(
        select(ExecutionLog)
        .where(ExecutionLog.task_id == task_id)
        .order_by(ExecutionLog.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    intrs = list(session.execute(
        select(Interruption)
        .where(Interruption.task_id == task_id)
        .order_by(Interruption.paused_at.asc())
    ).scalars())

    return TimingResponse(
        task_id=task.id,
        task_status=task.status,
        task_started_at=_as_utc(task.started_at),
        execution_log=ExecutionLogOut.model_validate(log) if log else None,
        interruptions=[InterruptionOut.model_validate(i) for i in intrs],
    )


@router.patch("/execution-log/{log_id}", response_model=ExecutionLogOut)
def patch_execution_log(
    log_id: int,
    body: ExecutionLogUpdate,
    session: Session = Depends(get_session),
) -> ExecutionLogOut:
    log = session.get(ExecutionLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"execution_log id={log_id} not found")

    if body.started_at is not None:
        log.started_at = body.started_at
    if body.finished_at is not None:
        log.finished_at = body.finished_at
    if body.completion_notes is not None:
        log.completion_notes = body.completion_notes

    # Recompute actual_minutes from the bounds unless the caller is explicitly
    # overriding it. Bounds always win when both move.
    if body.actual_minutes is not None:
        log.actual_minutes = body.actual_minutes
    elif body.started_at is not None or body.finished_at is not None:
        start = _as_utc(log.started_at)
        end = _as_utc(log.finished_at)
        if start and end and end > start:
            log.actual_minutes = max(0, int((end - start).total_seconds() // 60))

    session.commit()
    session.refresh(log)
    return ExecutionLogOut.model_validate(log)


@router.patch("/interruptions/{interruption_id}", response_model=InterruptionOut)
def patch_interruption(
    interruption_id: int,
    body: InterruptionUpdate,
    session: Session = Depends(get_session),
) -> InterruptionOut:
    intr = session.get(Interruption, interruption_id)
    if intr is None:
        raise HTTPException(
            status_code=404, detail=f"interruption id={interruption_id} not found"
        )

    if body.paused_at is not None:
        intr.paused_at = body.paused_at
    if body.resumed_at is not None:
        intr.resumed_at = body.resumed_at
    if body.reason is not None:
        intr.reason = body.reason

    session.commit()
    session.refresh(intr)
    return InterruptionOut.model_validate(intr)
