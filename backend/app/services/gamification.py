"""Phase 6b: gamification math. Tiny module — points and streak — but the
streak logic is timezone-sensitive so it has to live somewhere named.

Points (per-task):
  +5 on Start  (just for showing up)
  +20 on Done  (real reward for finishing)
  +10 on Done if it's the first completion today (in owner's local tz)

Streak (date-based, owner's local tz):
  - No previous completion → streak = 1
  - Last completion was today → streak unchanged
  - Last completion was exactly yesterday → streak += 1
  - Otherwise (gap of 2+ days) → streak resets to 1

This is intentionally lenient — Cadence shouldn't punish the user for skipping
a day. The longest_streak field preserves their record even after a reset.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import GamificationState, User

logger = logging.getLogger(__name__)

START_POINTS = 5
DONE_POINTS = 20
FIRST_OF_DAY_BONUS = 10


def _owner_tz(user: User) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(user.timezone or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        return zoneinfo.ZoneInfo("UTC")


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_date(dt: Optional[datetime], tz: zoneinfo.ZoneInfo):
    if dt is None:
        return None
    return _as_utc(dt).astimezone(tz).date()


def _get_or_create_state(session: Session, user_id: int) -> GamificationState:
    state = session.get(GamificationState, user_id)
    if state is None:
        state = GamificationState(
            user_id=user_id, points=0, current_streak=0, longest_streak=0
        )
        session.add(state)
        session.flush()
    return state


def award_start(session: Session, user_id: int) -> GamificationState:
    """User hit Start on a task. Small encouragement; no streak change."""
    state = _get_or_create_state(session, user_id)
    state.points += START_POINTS
    return state


def award_done(
    session: Session, user_id: int, *, now: Optional[datetime] = None
) -> GamificationState:
    """User hit Done. Award DONE_POINTS, +FIRST_OF_DAY_BONUS if this is the
    first completion today in owner's local tz, and update the streak."""
    now = now or datetime.now(timezone.utc)
    user = session.get(User, user_id)
    tz = _owner_tz(user)
    today_local = now.astimezone(tz).date()

    state = _get_or_create_state(session, user_id)
    last_local = _local_date(state.last_action_at, tz)

    is_first_of_day = last_local != today_local
    state.points += DONE_POINTS
    if is_first_of_day:
        state.points += FIRST_OF_DAY_BONUS

    # Streak math — only updates when this is the first done of the day.
    if last_local is None:
        state.current_streak = 1
    elif last_local == today_local:
        # Already counted today; streak unchanged.
        pass
    elif (today_local - last_local).days == 1:
        state.current_streak += 1
    else:
        # Gap of 2+ days — streak resets to today.
        state.current_streak = 1

    if state.current_streak > state.longest_streak:
        state.longest_streak = state.current_streak

    state.last_action_at = now
    logger.info(
        "gamification done user=%s points=%s streak=%s (longest=%s) first_of_day=%s",
        user_id, state.points, state.current_streak, state.longest_streak, is_first_of_day,
    )
    return state
