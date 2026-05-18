"""User-facing endpoints that don't fit anywhere else. For v1 just one:
push token registration. Phase 7+ may add an /me endpoint, timezone update, etc."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services.notifications import is_expo_push_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


class PushTokenRequest(BaseModel):
    push_token: str = Field(
        ...,
        description=(
            "Expo push token from `Notifications.getExpoPushTokenAsync()`. "
            "Must start with 'ExponentPushToken['. Pass an empty string to clear."
        ),
    )


@router.post("/users/{user_id}/push-token", status_code=204)
def set_push_token(
    user_id: int,
    body: PushTokenRequest,
    session: Session = Depends(get_session),
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user_id={user_id} not found")
    if body.push_token and not is_expo_push_token(body.push_token):
        raise HTTPException(
            status_code=422,
            detail="push_token must start with 'ExponentPushToken[' (or be empty to clear)",
        )
    user.push_token = body.push_token or None
    session.commit()
    logger.info("push token set user=%s present=%s", user_id, bool(user.push_token))
