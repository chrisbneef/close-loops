from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ScheduledBlockOut, ScheduleResponse
from app.services.scheduler import pack_for_owner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedule"])


@router.get("/schedule/{owner_id}", response_model=ScheduleResponse)
def get_schedule(
    owner_id: int,
    horizon_days: int = Query(14, ge=1, le=90),
    daily_capacity_minutes: int = Query(360, ge=30, le=720),
    session: Session = Depends(get_session),
) -> ScheduleResponse:
    """Compute and return the proposed schedule for an owner. No persistence yet
    (that lands in Phase 3b)."""
    now = datetime.now(timezone.utc)
    try:
        blocks, unscheduled = pack_for_owner(
            session,
            owner_id,
            now=now,
            horizon_days=horizon_days,
            daily_capacity_minutes=daily_capacity_minutes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return ScheduleResponse(
        owner_id=owner_id,
        generated_at=now,
        horizon_days=horizon_days,
        blocks=[
            ScheduledBlockOut(
                task_id=b.task_id, title=b.title, start=b.start, end=b.end, priority=b.priority
            )
            for b in blocks
        ],
        unscheduled_task_ids=unscheduled,
    )
