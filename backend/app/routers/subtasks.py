"""CRUD for SOP-style subtask checklists under a Task. Designed for the
Phase 8 widget UI but usable from anywhere.

  GET    /tasks/{task_id}/subtasks
  POST   /tasks/{task_id}/subtasks               body: {title, position?}
  PATCH  /tasks/{task_id}/subtasks/{subtask_id}  body: {title?, completed?, position?}
  DELETE /tasks/{task_id}/subtasks/{subtask_id}

Toggling `completed=true` via PATCH automatically stamps completed_at.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Task, TaskSubtask
from app.schemas import SubtaskCreate, SubtaskOut, SubtaskUpdate

router = APIRouter(tags=["subtasks"])


def _require_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")
    return task


@router.get("/tasks/{task_id}/subtasks", response_model=list[SubtaskOut])
def list_subtasks(task_id: int, session: Session = Depends(get_session)) -> list[SubtaskOut]:
    _require_task(session, task_id)
    rows = session.execute(
        select(TaskSubtask).where(TaskSubtask.task_id == task_id).order_by(TaskSubtask.position.asc())
    ).scalars().all()
    return [SubtaskOut.model_validate(r) for r in rows]


@router.post("/tasks/{task_id}/subtasks", response_model=SubtaskOut, status_code=201)
def create_subtask(
    task_id: int, body: SubtaskCreate, session: Session = Depends(get_session),
) -> SubtaskOut:
    _require_task(session, task_id)
    if body.position is None:
        max_pos = session.execute(
            select(func.max(TaskSubtask.position)).where(TaskSubtask.task_id == task_id)
        ).scalar()
        # `max_pos or -1` is wrong here — 0 is a valid existing position and
        # Python treats 0 as falsy. Check None explicitly.
        position = 0 if max_pos is None else max_pos + 1
    else:
        position = body.position
    subtask = TaskSubtask(task_id=task_id, title=body.title, position=position)
    session.add(subtask)
    session.commit()
    session.refresh(subtask)
    return SubtaskOut.model_validate(subtask)


@router.patch("/tasks/{task_id}/subtasks/{subtask_id}", response_model=SubtaskOut)
def update_subtask(
    task_id: int, subtask_id: int, body: SubtaskUpdate,
    session: Session = Depends(get_session),
) -> SubtaskOut:
    subtask = session.get(TaskSubtask, subtask_id)
    if subtask is None or subtask.task_id != task_id:
        raise HTTPException(
            status_code=404, detail=f"subtask_id={subtask_id} not found under task {task_id}"
        )
    if body.title is not None:
        subtask.title = body.title
    if body.position is not None:
        subtask.position = body.position
    if body.completed is not None and body.completed != subtask.completed:
        subtask.completed = body.completed
        subtask.completed_at = datetime.now(timezone.utc) if body.completed else None
    session.commit()
    session.refresh(subtask)
    return SubtaskOut.model_validate(subtask)


@router.delete("/tasks/{task_id}/subtasks/{subtask_id}", status_code=204)
def delete_subtask(
    task_id: int, subtask_id: int, session: Session = Depends(get_session),
) -> None:
    subtask = session.get(TaskSubtask, subtask_id)
    if subtask is None or subtask.task_id != task_id:
        raise HTTPException(
            status_code=404, detail=f"subtask_id={subtask_id} not found under task {task_id}"
        )
    session.delete(subtask)
    session.commit()
