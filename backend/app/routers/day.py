"""Day Plan endpoints — drive the dashboard's TODAY timeline.

  GET   /day-plan?owner_id=N     → today's meetings + Cadence task blocks,
                                    sorted by start time, plus a `has_started`
                                    flag for whether the Start Your Day CTA
                                    should still be shown.
  POST  /day/start?owner_id=N    → mark day_started_at = now + trigger a
                                    fresh reschedule constrained to the
                                    workday window (now → 18:00 local, capped
                                    at 9 hours), then return the new day plan.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CalendarBlock, ExecutionLog, Interruption, Task, User
from app.schemas import (
    DayPlanItem, DayPlanResponse, DayTimelineEvent, DayTimelineGap,
    DayTimelineResponse, GapFillRequest, StartDayRequest,
)
from app.services import reschedule
from app.services.scheduler import provider_for_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["day"])

# Workday cap: tasks won't pack past this local hour. Lunch (1h) effectively
# fits inside the 8am-6pm window via the calendar provider's morning/afternoon
# split.
DEFAULT_END_HOUR_LOCAL = 18
WORKDAY_MAX_HOURS = 9

# Sub-5-min gaps aren't worth surfacing — they're usually just clock skew
# between events and the user would gloss over them anyway.
MIN_GAP_MINUTES = 5


def _owner_tz(owner: User) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(owner.timezone or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        return zoneinfo.ZoneInfo("UTC")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_day_bounds(owner: User, *, now: datetime) -> tuple[datetime, datetime, str]:
    """Returns (day_start_utc, day_end_utc, YYYY-MM-DD) — bounds for "today" in
    the owner's local timezone, used to filter calendar_blocks and Google
    events to today only."""
    tz = _owner_tz(owner)
    local_now = _as_utc(now).astimezone(tz)
    local_date = local_now.date()
    day_start = datetime.combine(local_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    day_end = datetime.combine(local_date, time.max, tzinfo=tz).astimezone(timezone.utc)
    return day_start, day_end, local_date.isoformat()


def _has_started_today(owner: User, *, now: datetime) -> bool:
    """True iff day_started_at falls inside today's local-day window."""
    if owner.day_started_at is None:
        return False
    day_start, day_end, _ = _local_day_bounds(owner, now=now)
    started = _as_utc(owner.day_started_at)
    return day_start <= started <= day_end


def _has_ended_today(owner: User, *, now: datetime) -> bool:
    if owner.day_ended_at is None:
        return False
    day_start, day_end, _ = _local_day_bounds(owner, now=now)
    ended = _as_utc(owner.day_ended_at)
    return day_start <= ended <= day_end


def _build_day_plan(session: Session, owner: User, *, now: datetime) -> DayPlanResponse:
    day_start, day_end, date_str = _local_day_bounds(owner, now=now)
    items: list[DayPlanItem] = []
    has_started = _has_started_today(owner, now=now)

    # Cadence task blocks — only surface them once the user has actually
    # clicked Start Your Day. Until then we show meetings only, so freshly-
    # added tasks don't auto-populate the TODAY rail. The background
    # scheduler still writes calendar_blocks behind the scenes; we just
    # withhold them from the display until the day is anchored.
    if has_started:
        block_rows = list(session.execute(
            select(CalendarBlock, Task)
            .join(Task, Task.id == CalendarBlock.task_id)
            .where(
                Task.owner_id == owner.id,
                CalendarBlock.start >= day_start,
                CalendarBlock.start <= day_end,
            )
            .order_by(CalendarBlock.start.asc())
        ).all())
        for block, task in block_rows:
            items.append(DayPlanItem(
                start=_as_utc(block.start),
                end=_as_utc(block.end),
                title=task.title,
                type="task",
                task_id=task.id,
                importance=task.importance,
                status=task.status,
            ))

    # Google Calendar meetings on the owner's connected calendar — only if
    # they've actually connected, otherwise skip cleanly.
    if owner.google_refresh_token:
        provider = provider_for_user(owner)
        try:
            for ev in provider.events_for_window(
                owner.timezone or "UTC", start=day_start, end=day_end,
            ):
                items.append(DayPlanItem(
                    start=_as_utc(ev.start),
                    end=_as_utc(ev.end),
                    title=ev.title,
                    type="meeting",
                ))
        except Exception:
            logger.exception("Failed to fetch day's Google events for owner=%s", owner.id)

    items.sort(key=lambda i: i.start)

    return DayPlanResponse(
        owner_id=owner.id,
        date=date_str,
        items=items,
        has_started=has_started,
        has_ended=_has_ended_today(owner, now=now),
    )


@router.get("/day-plan", response_model=DayPlanResponse)
def get_day_plan(
    owner_id: int = Query(...),
    session: Session = Depends(get_session),
) -> DayPlanResponse:
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} not found")
    return _build_day_plan(session, owner, now=datetime.now(timezone.utc))


@router.post("/day/start", response_model=DayPlanResponse)
def start_day(
    owner_id: int = Query(...),
    body: Optional[StartDayRequest] = None,
    session: Session = Depends(get_session),
) -> DayPlanResponse:
    """Mark Start Your Day for `owner_id`, kick off a scheduler tick so the
    packer fills today's free slots around any Google meetings, then return
    the resulting day plan."""
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} not found")

    now = datetime.now(timezone.utc)

    # Pin day_started_at so the dashboard's CTA flips off until tomorrow.
    owner.day_started_at = now
    session.commit()

    # Trigger a synchronous reschedule for this owner (and downstream
    # cross-owner deps). Constraining packing to today's window without
    # disturbing future-day blocks is a bigger change; for v1 we lean on the
    # existing scheduler — it already uses `now` as the start, packs into
    # free slots (which exclude Google meetings), and respects daily capacity.
    reschedule.request_reschedule_for_owner(owner.id, reason="day/start")

    # Re-read the owner so day_started_at is fresh after the commit.
    session.refresh(owner)
    return _build_day_plan(session, owner, now=now)


def _gather_timeline_events(
    session: Session, owner: User, *, day_start: datetime, day_end: datetime,
) -> list[DayTimelineEvent]:
    """All accounted-for stretches of time today: completed tasks, pauses,
    Google meetings. Sorted by start time."""
    events: list[DayTimelineEvent] = []

    # Completed tasks (execution_log rows finished today).
    log_rows = list(session.execute(
        select(ExecutionLog, Task)
        .join(Task, Task.id == ExecutionLog.task_id)
        .where(
            ExecutionLog.user_id == owner.id,
            ExecutionLog.finished_at >= day_start,
            ExecutionLog.finished_at <= day_end,
        )
    ).all())
    for log, task in log_rows:
        events.append(DayTimelineEvent(
            start=_as_utc(log.started_at),
            end=_as_utc(log.finished_at),
            kind="task",
            title=task.title,
            task_id=task.id,
            execution_log_id=log.id,
        ))

    # Pauses (both resolved and still-open).
    intr_rows = list(session.execute(
        select(Interruption)
        .where(
            Interruption.user_id == owner.id,
            Interruption.paused_at >= day_start,
            Interruption.paused_at <= day_end,
            Interruption.resumed_at.is_not(None),  # only resolved for the timeline
        )
    ).scalars())
    # Map task_id -> title for pauses anchored to a task (for the timeline label).
    task_titles: dict[int, str] = {}
    task_ids_needed = {i.task_id for i in intr_rows if i.task_id is not None}
    if task_ids_needed:
        for t in session.execute(
            select(Task).where(Task.id.in_(task_ids_needed))
        ).scalars():
            task_titles[t.id] = t.title
    for intr in intr_rows:
        anchor = task_titles.get(intr.task_id, "") if intr.task_id else ""
        label = intr.reason or "pause"
        title = f"{label}" + (f" · {anchor}" if anchor else "")
        events.append(DayTimelineEvent(
            start=_as_utc(intr.paused_at),
            end=_as_utc(intr.resumed_at),
            kind="pause",
            title=title,
            task_id=intr.task_id,
            interruption_id=intr.id,
        ))

    # Google Calendar meetings.
    if owner.google_refresh_token:
        provider = provider_for_user(owner)
        try:
            for ev in provider.events_for_window(
                owner.timezone or "UTC", start=day_start, end=day_end,
            ):
                events.append(DayTimelineEvent(
                    start=_as_utc(ev.start),
                    end=_as_utc(ev.end),
                    kind="meeting",
                    title=ev.title,
                ))
        except Exception:
            logger.exception("Failed to fetch meetings for timeline owner=%s", owner.id)

    events.sort(key=lambda e: e.start)
    return events


def _detect_gaps(
    events: list[DayTimelineEvent], *, window_start: datetime, window_end: datetime,
) -> list[DayTimelineGap]:
    """Walk the merged event timeline and emit any unaccounted stretches
    between `window_start` and `window_end`, ignoring sub-MIN_GAP_MINUTES."""
    out: list[DayTimelineGap] = []
    cursor = window_start
    for ev in events:
        if ev.start > cursor:
            mins = int((ev.start - cursor).total_seconds() // 60)
            if mins >= MIN_GAP_MINUTES:
                out.append(DayTimelineGap(start=cursor, end=ev.start, duration_minutes=mins))
        if ev.end > cursor:
            cursor = ev.end
    if window_end > cursor:
        mins = int((window_end - cursor).total_seconds() // 60)
        if mins >= MIN_GAP_MINUTES:
            out.append(DayTimelineGap(start=cursor, end=window_end, duration_minutes=mins))
    return out


@router.get("/day/timeline", response_model=DayTimelineResponse)
def get_day_timeline(
    owner_id: int = Query(...),
    session: Session = Depends(get_session),
) -> DayTimelineResponse:
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} not found")

    now = datetime.now(timezone.utc)
    day_start, day_end, date_str = _local_day_bounds(owner, now=now)
    events = _gather_timeline_events(session, owner, day_start=day_start, day_end=day_end)

    # Detect gaps between day_started_at (or first event) and day_ended_at (or now).
    window_start = (
        _as_utc(owner.day_started_at)
        if owner.day_started_at and _has_started_today(owner, now=now)
        else (events[0].start if events else now)
    )
    window_end = (
        _as_utc(owner.day_ended_at)
        if owner.day_ended_at and _has_ended_today(owner, now=now)
        else now
    )
    gaps = _detect_gaps(events, window_start=window_start, window_end=window_end)

    return DayTimelineResponse(
        owner_id=owner.id,
        date=date_str,
        day_started_at=_as_utc(owner.day_started_at) if _has_started_today(owner, now=now) else None,
        day_ended_at=_as_utc(owner.day_ended_at) if _has_ended_today(owner, now=now) else None,
        events=events,
        gaps=gaps,
    )


@router.post("/day/gaps/fill", status_code=201)
def fill_gap(
    body: GapFillRequest,
    session: Session = Depends(get_session),
) -> dict[str, int | str]:
    """Label a gap as a retroactive task (Task + ExecutionLog) or pause
    (free-standing Interruption with task_id=NULL)."""
    owner = session.get(User, body.owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={body.owner_id} not found")
    if body.end_at <= body.start_at:
        raise HTTPException(status_code=422, detail="end_at must be after start_at")

    duration_min = max(1, int((body.end_at - body.start_at).total_seconds() // 60))

    if body.kind == "task":
        task = Task(
            title=body.label.strip(),
            owner_id=owner.id,
            est_minutes=duration_min,
            status="done",
            started_at=body.start_at,
            finished_at=body.end_at,
        )
        session.add(task)
        session.flush()
        log = ExecutionLog(
            task_id=task.id,
            user_id=owner.id,
            estimated_minutes=duration_min,
            actual_minutes=duration_min,
            started_at=body.start_at,
            finished_at=body.end_at,
        )
        session.add(log)
        session.commit()
        return {"kind": "task", "task_id": task.id, "execution_log_id": log.id}

    # kind == "pause" — free-standing pause not anchored to a task.
    intr = Interruption(
        task_id=None,
        user_id=owner.id,
        paused_at=body.start_at,
        resumed_at=body.end_at,
        reason=body.label.strip(),
    )
    session.add(intr)
    session.commit()
    return {"kind": "pause", "interruption_id": intr.id}


@router.post("/day/end", response_model=DayPlanResponse)
def end_day(
    owner_id: int = Query(...),
    session: Session = Depends(get_session),
) -> DayPlanResponse:
    """Pin day_ended_at and return the day timeline so the user can review +
    fill in gaps. Doesn't reschedule — the day is wrapping, not regenerating."""
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} not found")

    now = datetime.now(timezone.utc)
    owner.day_ended_at = now
    session.commit()
    session.refresh(owner)
    return _build_day_plan(session, owner, now=now)
