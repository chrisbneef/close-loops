"""Execution analytics — daily & weekly memo-style reports.

Both endpoints return a PeriodReport: completion stats (on-time / over-estimate),
what didn't get done (overdue + scheduled-but-unfinished), decayed tasks, a
pause/distraction rollup, and a narrative `memo` written by Claude (best-effort;
falls back to a deterministic summary if the LLM isn't configured).

  GET /reports/daily?owner_id=N   → the owner's current local day so far
  GET /reports/weekly?owner_id=N  → rolling window_days (default 7)
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.schemas import PeriodReport
from app.services import report_memo, reporting
from app.services.llm import LLMNotConfigured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

DEFAULT_WINDOW_DAYS = 7


def _owner_tz(owner: User) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(owner.timezone or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        return zoneinfo.ZoneInfo("UTC")


def _attach_memo(report: PeriodReport, owner: User, want_memo: bool) -> None:
    if not want_memo:
        return
    try:
        report.memo = report_memo.generate_memo(report, owner.name)
    except LLMNotConfigured:
        report.memo = report_memo.fallback_memo(report, owner.name)
    except Exception:
        logger.exception("report memo generation failed; using fallback")
        report.memo = report_memo.fallback_memo(report, owner.name)


@router.get("/reports/daily", response_model=PeriodReport)
def get_daily_report(
    owner_id: int,
    end_date: Optional[datetime] = Query(None, description="End of the day window (UTC). Defaults to now."),
    memo: bool = Query(True, description="Generate the narrative memo (1 LLM call). Set false for stats only."),
    session: Session = Depends(get_session),
) -> PeriodReport:
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")

    tz = _owner_tz(owner)
    end = end_date or datetime.now(timezone.utc)
    # Start of the owner's local day containing `end`.
    local_end = end.astimezone(tz)
    start = datetime.combine(local_end.date(), time.min, tzinfo=tz).astimezone(timezone.utc)

    report = reporting.build_report(session, owner_id, granularity="daily", start=start, end=end)
    _attach_memo(report, owner, memo)
    return report


@router.get("/reports/weekly", response_model=PeriodReport)
def get_weekly_report(
    owner_id: int,
    end_date: Optional[datetime] = Query(None, description="End of the window (inclusive). Defaults to now. UTC."),
    window_days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=90, description="Window size in days. Default 7."),
    memo: bool = Query(True, description="Generate the narrative memo (1 LLM call). Set false for stats only."),
    session: Session = Depends(get_session),
) -> PeriodReport:
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")

    end = end_date or datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)

    report = reporting.build_report(session, owner_id, granularity="weekly", start=start, end=end)
    _attach_memo(report, owner, memo)
    return report
