"""Gamification math + endpoint tests. Covers point awards, streak
continuation, streak reset, multi-task-per-day, owner isolation, and the
/start hook awarding without touching streak."""

from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.services import gamification
from app.services.gamification import (
    DONE_POINTS,
    FIRST_OF_DAY_BONUS,
    START_POINTS,
    award_done,
    award_start,
)

# A weekday morning in UTC; cofounders fixture uses tz="UTC" so dates line up.
DAY1 = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
DAY2 = DAY1 + timedelta(days=1)
DAY3 = DAY1 + timedelta(days=2)


# ---------- single-shot point math ----------

def test_start_awards_small_points(session, cofounders):
    michael, _ = cofounders
    state = award_start(session, michael.id)
    session.commit()
    assert state.points == START_POINTS
    assert state.current_streak == 0  # start doesn't touch streak


def test_first_done_awards_done_plus_first_of_day(session, cofounders):
    michael, _ = cofounders
    state = award_done(session, michael.id, now=DAY1)
    session.commit()
    assert state.points == DONE_POINTS + FIRST_OF_DAY_BONUS
    assert state.current_streak == 1
    assert state.longest_streak == 1


def test_second_done_same_day_no_bonus_no_streak_bump(session, cofounders):
    michael, _ = cofounders
    award_done(session, michael.id, now=DAY1)
    session.commit()
    state = award_done(session, michael.id, now=DAY1 + timedelta(hours=2))
    session.commit()
    # First done: DONE + FIRST_OF_DAY = 30. Second done same day: just DONE = 20. Total = 50.
    assert state.points == 2 * DONE_POINTS + FIRST_OF_DAY_BONUS
    assert state.current_streak == 1  # unchanged


# ---------- streak continuation ----------

def test_consecutive_days_extend_streak(session, cofounders):
    michael, _ = cofounders
    award_done(session, michael.id, now=DAY1)
    session.commit()
    state = award_done(session, michael.id, now=DAY2)
    session.commit()
    assert state.current_streak == 2
    assert state.longest_streak == 2

    state = award_done(session, michael.id, now=DAY3)
    session.commit()
    assert state.current_streak == 3
    assert state.longest_streak == 3


def test_two_day_gap_resets_streak_but_preserves_longest(session, cofounders):
    michael, _ = cofounders
    award_done(session, michael.id, now=DAY1)
    award_done(session, michael.id, now=DAY2)
    session.commit()  # streak now 2

    # Skip DAY3, complete on DAY4 (gap of 2 days from DAY2).
    state = award_done(session, michael.id, now=DAY1 + timedelta(days=3))
    session.commit()
    assert state.current_streak == 1  # reset
    assert state.longest_streak == 2  # preserved


# ---------- timezone-aware streak ----------

def test_streak_respects_owner_timezone(session):
    """Two completions a few hours apart in UTC but on different LOCAL days
    in the user's timezone should NOT both count as 'today'."""
    user = models.User(name="Pacific user", role="cofounder",
                       timezone="America/Los_Angeles")
    session.add(user)
    session.commit()

    # Completion 1: 2026-05-18 06:00 UTC = 2026-05-17 23:00 PT (still Sunday in PT)
    award_done(session, user.id, now=datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc))
    session.commit()

    # Completion 2: 2026-05-18 10:00 UTC = 2026-05-18 03:00 PT (Monday in PT)
    # In LOCAL terms this is "next day" → streak should bump to 2.
    state = award_done(session, user.id, now=datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc))
    session.commit()
    assert state.current_streak == 2  # crossed local midnight


# ---------- owner isolation ----------

def test_owner_isolation(session, cofounders):
    michael, chris = cofounders
    award_done(session, michael.id, now=DAY1)
    award_done(session, michael.id, now=DAY2)
    award_done(session, chris.id, now=DAY1)
    session.commit()

    m_state = session.get(models.GamificationState, michael.id)
    c_state = session.get(models.GamificationState, chris.id)
    assert m_state.current_streak == 2
    assert c_state.current_streak == 1
    # Michael had 2 done events: each got DONE + (first-of-day) bonus.
    assert m_state.points == 2 * (DONE_POINTS + FIRST_OF_DAY_BONUS)
    assert c_state.points == DONE_POINTS + FIRST_OF_DAY_BONUS


# ---------- endpoint ----------

def test_get_gamification_endpoint_returns_zeros_when_never_played(client_with_users):
    c = client_with_users
    r = c.get("/gamification?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == 0
    assert body["current_streak"] == 0
    assert body["longest_streak"] == 0
    assert body["last_action_at"] is None


def test_get_gamification_404_on_unknown_owner(client_with_users):
    r = client_with_users.get("/gamification?owner_id=9999")
    assert r.status_code == 404


# ---------- minimal fixture for the endpoint tests ----------

@pytest.fixture
def client_with_users(session, cofounders):
    """A TestClient that uses the same in-memory engine as the session fixture."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_session

    def _override():
        try:
            yield session
        finally:
            pass  # session lifecycle managed by the conftest fixture

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
