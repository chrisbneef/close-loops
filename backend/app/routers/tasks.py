"""Manual task creation — the widget's +task button.

POST /tasks creates a single task directly (no LLM decomposition — that's
/ingest's job) and appends a locked calendar_block right after the owner's
current schedule so the task surfaces immediately in /next-action, even when
the owner's real calendar is fully booked (the locked block survives the
scheduler's re-pack).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CalendarBlock, Interruption, Task, TaskSubtask, User
from app.schemas import SubtaskOut, TaskCreate, TaskOut, TaskUpdate
from app.services import reschedule

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])

# Statuses shown on the board / returned by GET /tasks (everything but the
# soft-tombstone 'decayed'). 'whiteboard' is the parked-idea backlog column.
BOARD_STATUSES = ("whiteboard", "pending", "scheduled", "in_progress", "paused", "done")

# Neutral/backward statuses PATCH /tasks/{id} may set directly. Forward moves
# (in_progress/paused/done) must go through /start, /pause, /done.
PATCHABLE_STATUSES = ("whiteboard", "pending", "scheduled")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _with_subtasks(session: Session, tasks: list[Task]) -> list[TaskOut]:
    """Embed each task's subtasks so the board doesn't N+1 fetch."""
    if not tasks:
        return []
    ids = [t.id for t in tasks]
    rows = list(session.execute(
        select(TaskSubtask).where(TaskSubtask.task_id.in_(ids)).order_by(TaskSubtask.position.asc())
    ).scalars())
    by_task: dict[int, list[SubtaskOut]] = {}
    for sub in rows:
        by_task.setdefault(sub.task_id, []).append(SubtaskOut.model_validate(sub))
    out: list[TaskOut] = []
    for t in tasks:
        to = TaskOut.model_validate(t)
        to.subtasks = by_task.get(t.id, [])
        out.append(to)
    return out


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, session: Session = Depends(get_session)) -> TaskOut:
    owner = session.get(User, body.owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={body.owner_id} does not exist")

    task = Task(
        title=body.title,
        owner_id=body.owner_id,
        est_minutes=body.est_minutes,
        importance=body.importance,
        deadline=body.deadline,
        status=body.status,
    )
    session.add(task)
    session.flush()

    # A committed (pending) task gets a locked block right after the owner's
    # last scheduled block so it reliably surfaces in /next-action even on a
    # full calendar. A parked whiteboard idea gets NO block — it's captured,
    # not scheduled, until the user promotes it.
    if body.status == "pending":
        now = datetime.now(timezone.utc)
        last_end = session.execute(
            select(func.max(CalendarBlock.end))
            .join(Task, Task.id == CalendarBlock.task_id)
            .where(Task.owner_id == body.owner_id)
        ).scalar()
        start = max(_as_utc(last_end), now) if last_end is not None else now
        session.add(CalendarBlock(
            task_id=task.id,
            start=start,
            end=start + timedelta(minutes=body.est_minutes),
            locked=True,
        ))
    session.commit()
    session.refresh(task)
    logger.info(
        "manual task created task_id=%s owner_id=%s status=%s title=%r",
        task.id, owner.id, task.status, task.title,
    )
    return TaskOut.model_validate(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    owner_id: int,
    done_within_days: int = Query(7, ge=0, le=365, description="Cap the Done column: only include done tasks finished within this many days."),
    session: Session = Depends(get_session),
) -> list[TaskOut]:
    """All of an owner's board-visible tasks (every status but 'decayed'),
    subtasks embedded. The frontend buckets these into Kanban columns by
    status. Done tasks are capped to a recent window so the Done column
    doesn't grow forever."""
    if session.get(User, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")

    cutoff = datetime.now(timezone.utc) - timedelta(days=done_within_days)
    rows = list(session.execute(
        select(Task)
        .where(
            Task.owner_id == owner_id,
            Task.status.in_(BOARD_STATUSES),
            # done tasks only if recently finished; non-done always included
            or_(Task.status != "done", Task.finished_at >= cutoff),
        )
        .order_by(Task.importance.desc(), Task.id.asc())
    ).scalars())
    return _with_subtasks(session, rows)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: int, body: TaskUpdate, session: Session = Depends(get_session),
) -> TaskOut:
    """Edit fields and/or move a task backward/neutral to 'whiteboard'/'pending'/
    'scheduled' (Kanban click-to-move). Forward transitions (in_progress/paused/
    done) are rejected with 409 — use /start, /pause, /done so their side effects
    fire."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task_id={task_id} not found")

    if body.title is not None:
        task.title = body.title
    if body.importance is not None:
        task.importance = body.importance
    if body.est_minutes is not None:
        task.est_minutes = body.est_minutes
    if body.deadline is not None:
        task.deadline = body.deadline

    moved = False
    if body.status is not None and body.status != task.status:
        # Schema already constrains body.status, but guard anyway.
        if body.status not in PATCHABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Use /tasks/{id}/start, /pause, or /done for in_progress/paused/done.",
            )
        # Moving back from an active state: clear the run stamp + close any open interruption.
        if task.status in ("in_progress", "paused"):
            task.started_at = None
            open_intr = session.execute(
                select(Interruption).where(
                    Interruption.task_id == task.id, Interruption.resumed_at.is_(None)
                )
            ).scalars().all()
            for intr in open_intr:
                intr.resumed_at = datetime.now(timezone.utc)
        # Parking to the whiteboard: strip any calendar presence. Unlock the
        # task's blocks first so the reschedule's diff deletes them (incl. the
        # Google event) — locked blocks are otherwise preserved.
        if body.status == "whiteboard":
            blocks = session.execute(
                select(CalendarBlock).where(CalendarBlock.task_id == task.id)
            ).scalars().all()
            for b in blocks:
                b.locked = False
        task.status = body.status
        moved = True

    session.commit()
    session.refresh(task)

    if moved:
        reschedule.request_reschedule_for_owner(task.owner_id, reason=f"patch task {task_id} → {task.status}")

    return _with_subtasks(session, [task])[0]
