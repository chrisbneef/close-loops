"""Auth endpoints (Phase 8).

  POST /auth/login   {email, password} → {access_token, token_type, user}
  GET  /auth/me      (Bearer)          → the current user

Login identifies WHICH cofounder you are. The app is a shared two-person system
(body-doubling, partner presence, cross-owner delegation, the dashboard owner
toggle all depend on seeing each other), so a valid login gates access to the
whole team's data rather than isolating per user — but every request must now
carry a token, closing the anonymous-access hole.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.security import get_current_user
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    # Case-insensitive email match — users won't remember the exact casing.
    user = session.execute(
        select(User).where(func.lower(User.email) == body.email.strip().lower())
    ).scalar_one_or_none()

    # Verify even when the user is missing / has no hash, to keep the response
    # time roughly constant and not leak which emails exist.
    ok = auth_service.verify_password(
        body.password, user.password_hash if user else None
    )
    if not user or not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    try:
        token = auth_service.create_access_token(user.id)
    except auth_service.AuthNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured — set AUTH_SECRET in backend/.env.",
        )

    logger.info("login user_id=%s email=%s", user.id, user.email)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
