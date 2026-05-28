"""Auth dependency (Phase 8). `get_current_user` reads the Bearer token, decodes
it, and loads the User — attach it to routers to require a valid login.

Used two ways:
  - `dependencies=[Depends(get_current_user)]` on a router → just gate access.
  - `user: User = Depends(get_current_user)` in a handler → also use the identity.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services import auth as auth_service

# auto_error=False so we can return 401 (unauthenticated) for a missing header
# rather than HTTPBearer's default 403.
_bearer = HTTPBearer(auto_error=False)

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if creds is None or not creds.credentials:
        raise _UNAUTH
    try:
        user_id = auth_service.decode_access_token(creds.credentials)
    except auth_service.AuthNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured — set AUTH_SECRET in backend/.env.",
        )
    except jwt.PyJWTError:
        raise _UNAUTH
    user = session.get(User, user_id)
    if user is None:
        raise _UNAUTH
    return user
