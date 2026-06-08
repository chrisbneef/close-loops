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
from app.models import CalendarBlock, Task, User
from app.schemas import DayPlanItem, DayPlanResponse, StartDayRequest
from app.services import reschedule
from app.services.scheduler import provider_for_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["day"])

# Workday cap: tasks won't pack past this local hour. Lunch (1h) effectively
# fits inside the 8am-6pm window via the calendar provider's morning/afternoon
# split.
DEFAULT_END_HOUR_LOCAL = 18
WORKDAY_MAX_HOURS = 9


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


def _build_day_plan(session: Session, owner: User, *, now: datetime) -> DayPlanResponse:
    day_start, day_end, date_str = _local_day_bounds(owner, now=now)
    items: list[DayPlanItem] = []

    # Cadence task blocks scheduled for today.
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
        has_started=_has_started_today(owner, now=now),
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
