"""Read endpoint for the user's gamification counters. Writes happen as side
effects of /tasks/{id}/start and /tasks/{id}/done — there's no separate
"add point" endpoint, by design (the only way to earn is to work)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import GamificationState, User
from app.schemas import GamificationOut

router = APIRouter(tags=["gamification"])


@router.get("/gamification", response_model=GamificationOut)
def get_gamification(owner_id: int, session: Session = Depends(get_session)) -> GamificationOut:
    if session.get(User, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")
    state = session.get(GamificationState, owner_id)
    if state is None:
        # User has never started or completed a task — return zeros, not 404.
        return GamificationOut(user_id=owner_id, points=0, current_streak=0, longest_streak=0)
    return GamificationOut.model_validate(state)
