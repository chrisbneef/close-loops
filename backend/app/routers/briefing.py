"""Daily briefing endpoint.

Per the spec: "expose the briefing as a plain GET endpoint so any scheduler
can consume it." This lets you either:
  - Let an in-process APScheduler cron fire it at 6am daily, OR
  - Have your existing N8N / Zoho automation hit this endpoint on whatever
    schedule you want (recommended — gives you one source of cron truth)

GET /briefing/today?owner_id=N&post_to_slack=true
  → { briefing: str, posted_to_slack: bool, data: BriefingData }
"""

from __future__ import annotations

import logging
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services import briefing, slack
from app.services.llm import LLMNotConfigured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["briefing"])


class BriefingResponse(BaseModel):
    owner_id: int
    briefing: str
    posted_to_slack: bool
    yesterday_completed_count: int
    today_scheduled_count: int
    current_streak: int


@router.get("/briefing/today", response_model=BriefingResponse)
def get_briefing_today(
    owner_id: int,
    post_to_slack: bool = Query(True, description="If true and SLACK_WEBHOOK_URL is set, also post the briefing."),
    session: Session = Depends(get_session),
) -> BriefingResponse:
    owner = session.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")

    data = briefing.gather(session, owner)

    try:
        text = briefing.generate(data)
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except anthropic.APIError as e:
        logger.exception("Anthropic API failure during briefing")
        raise HTTPException(status_code=502, detail=f"LLM failure: {e!s}") from e

    posted = False
    if post_to_slack:
        try:
            posted = slack.post_message(f"*Cadence briefing for {owner.name}*\n{text}")
        except slack.SlackError as e:
            logger.warning("slack post failed, returning briefing anyway: %s", e)

    return BriefingResponse(
        owner_id=owner.id,
        briefing=text,
        posted_to_slack=posted,
        yesterday_completed_count=len(data.yesterday_completed),
        today_scheduled_count=len(data.today_scheduled),
        current_streak=data.current_streak,
    )
