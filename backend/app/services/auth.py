"""Auth primitives (Phase 8): password hashing + session JWTs.

Kept dependency-light: `bcrypt` for hashing, `pyjwt` for stateless tokens.
No session table — a valid signed JWT *is* the session. Fine for a two-person
internal tool; if we ever need server-side revocation we add a token-version
column to users and check it here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


class AuthNotConfigured(RuntimeError):
    """Raised when AUTH_SECRET is unset — surfaced as a 503 by the router."""


def hash_password(plain: str) -> str:
    """bcrypt hash. bcrypt silently truncates at 72 bytes, so reject longer
    inputs rather than hashing a prefix and giving a false sense of strength."""
    raw = plain.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash — treat as a failed check, never raise.
        return False


def _require_secret() -> str:
    if not settings.auth_secret:
        raise AuthNotConfigured(
            "AUTH_SECRET is not set — cannot issue or verify session tokens."
        )
    return settings.auth_secret


def create_access_token(user_id: int) -> str:
    secret = _require_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.auth_token_ttl_days)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int:
    """Returns the user_id (`sub`). Raises jwt.PyJWTError on invalid/expired."""
    secret = _require_secret()
    payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    return int(payload["sub"])
