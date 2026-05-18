"""Body-doubling presence — read + write helpers around the `presence` table.

The spec is explicit that this should be *ambient, not surveillant*: each
cofounder sees the other's current state without any need to interact. The
table is already in the schema (Phase 1) — this module wires it up.

Status values come from PRESENCE_STATUSES in models.py:
  focusing | idle | offline

Staleness rule: if updated_at is older than STALE_AFTER_MINUTES, the read
helper returns the stored row but with status forced to 'offline'. This
prevents ghost-status when the app crashes or the phone loses connectivity
without sending a clean status update.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Presence, User

logger = logging.getLogger(__name__)

STALE_AFTER_MINUTES = 5
ACTIVE_STATUSES = ("focusing", "idle")
ALL_STATUSES = ("focusing", "idle", "offline")


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def update_presence(
    session: Session,
    user_id: int,
    *,
    status: str,
    current_task_id: Optional[int] = None,
) -> Presence:
    """Upsert presence for a user. Caller commits."""
    if status not in ALL_STATUSES:
        raise ValueError(f"status must be one of {ALL_STATUSES}, got {status!r}")
    row = session.get(Presence, user_id)
    if row is None:
        row = Presence(user_id=user_id, status=status, current_task_id=current_task_id)
        session.add(row)
    else:
        row.status = status
        row.current_task_id = current_task_id
    return row


def get_effective_presence(
    session: Session, user_id: int, *, now: Optional[datetime] = None
) -> Optional[Presence]:
    """Returns the stored row with staleness applied — status forced to
    'offline' if updated_at is older than STALE_AFTER_MINUTES. Returns None
    if the user has never had a presence row."""
    row = session.get(Presence, user_id)
    if row is None:
        return None
    now = now or datetime.now(timezone.utc)
    updated = _as_utc(row.updated_at)
    if updated and (now - updated) > timedelta(minutes=STALE_AFTER_MINUTES):
        # Don't mutate the stored row (next heartbeat from the user
        # would clobber the offline anyway). Return a detached copy
        # with offline status for the API response.
        row = Presence(
            user_id=row.user_id,
            status="offline",
            current_task_id=None,
        )
        row.updated_at = updated  # preserve so the client can show "last seen"
    return row


def find_partner(session: Session, owner_id: int) -> Optional[User]:
    """For the 2-cofounder model: the OTHER cofounder. Returns None if none
    exists (solo team, or owner not a cofounder)."""
    return session.execute(
        select(User)
        .where(User.role == "cofounder", User.id != owner_id)
        .order_by(User.id)
        .limit(1)
    ).scalar_one_or_none()
