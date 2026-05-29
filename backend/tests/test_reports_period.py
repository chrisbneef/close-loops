"""Daily/weekly memo reports — the additive parts beyond the original weekly
stats: daily windowing, 'what didn't get done', pause rollup, and the memo
(deterministic fallback, since conftest clears the Anthropic key)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app

# Fixed window so the daily/weekly math is deterministic regardless of real clock.
END = datetime(2026, 5, 29, 18, 0, tzinfo=timezone.utc)
# Query string form — 'Z' suffix avoids the '+' in '+00:00' decoding to a space.
ENDQ = "2026-05-29T18:00:00Z"
TODAY_9AM = datetime(2026, 5, 29, 9, 0, tzinfo=timezone.utc)
YESTERDAY = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", email="m@x.com", timezone="UTC"))
        s.commit()

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app), SessionLocal
    app.dependency_overrides.clear()


def _completed_task(s, *, title, est=30, actual=30, finished, deadline=None, importance=5):
    t = models.Task(title=title, owner_id=1, est_minutes=est, importance=importance,
                     status="done", deadline=deadline, started_at=finished - timedelta(minutes=actual),
                     finished_at=finished)
    s.add(t); s.flush()
    s.add(models.ExecutionLog(
        task_id=t.id, user_id=1, estimated_minutes=est, actual_minutes=actual,
        started_at=finished - timedelta(minutes=actual), finished_at=finished,
    ))
    return t


def test_daily_window_only_includes_today(client):
    c, SL = client
    with SL() as s:
        _completed_task(s, title="done today", finished=TODAY_9AM)
        _completed_task(s, title="done yesterday", finished=YESTERDAY)
        s.commit()

    r = c.get(f"/reports/daily?owner_id=1&end_date={ENDQ}&memo=false")
    assert r.status_code == 200
    body = r.json()
    assert body["granularity"] == "daily"
    assert body["total_completed"] == 1  # yesterday's is outside today's window
    assert body["rows"][0]["title"] == "done today"


def test_weekly_window_includes_both(client):
    c, SL = client
    with SL() as s:
        _completed_task(s, title="done today", finished=TODAY_9AM)
        _completed_task(s, title="done yesterday", finished=YESTERDAY)
        s.commit()

    r = c.get(f"/reports/weekly?owner_id=1&end_date={ENDQ}&memo=false")
    assert r.json()["total_completed"] == 2
    assert r.json()["granularity"] == "weekly"


def test_incomplete_includes_scheduled_and_overdue(client):
    c, SL = client
    with SL() as s:
        # Scheduled within the window, not done.
        scheduled = models.Task(title="slotted but unfinished", owner_id=1, status="pending", importance=6)
        s.add(scheduled); s.flush()
        s.add(models.CalendarBlock(task_id=scheduled.id, start=TODAY_9AM, end=TODAY_9AM + timedelta(minutes=30)))
        # Overdue, no block.
        s.add(models.Task(title="overdue thing", owner_id=1, status="pending",
                          deadline=YESTERDAY, importance=9))
        s.commit()

    body = c.get(f"/reports/daily?owner_id=1&end_date={ENDQ}&memo=false").json()
    titles = {row["title"]: row for row in body["incomplete"]}
    assert "slotted but unfinished" in titles
    assert "overdue thing" in titles
    assert titles["overdue thing"]["overdue"] is True
    # Overdue sorts first.
    assert body["incomplete"][0]["title"] == "overdue thing"


def test_pause_rollup_and_biggest_distraction(client):
    c, SL = client
    with SL() as s:
        t = models.Task(title="focus task", owner_id=1, status="in_progress")
        s.add(t); s.flush()
        for reason, when in [("slack ping", TODAY_9AM), ("slack ping", TODAY_9AM + timedelta(hours=1)),
                             ("coffee", TODAY_9AM + timedelta(hours=2))]:
            s.add(models.Interruption(task_id=t.id, user_id=1, paused_at=when,
                                      resumed_at=when + timedelta(minutes=5), reason=reason))
        s.commit()

    body = c.get(f"/reports/daily?owner_id=1&end_date={ENDQ}&memo=false").json()
    assert body["total_pauses"] == 3
    assert body["pause_reasons"]["slack ping"] == 2
    assert body["biggest_distraction"] == "slack ping"
    assert body["total_pause_minutes"] == 15


def test_memo_fallback_is_present_when_llm_unconfigured(client):
    c, SL = client
    with SL() as s:
        _completed_task(s, title="shipped it", finished=TODAY_9AM)
        s.commit()

    # memo defaults to true; conftest clears the key, so we get the deterministic fallback.
    body = c.get(f"/reports/daily?owner_id=1&end_date={ENDQ}").json()
    assert body["memo"]
    assert "completed 1 task" in body["memo"].lower()


def test_memo_false_returns_null_memo(client):
    c, _ = client
    body = c.get(f"/reports/daily?owner_id=1&end_date={ENDQ}&memo=false").json()
    assert body["memo"] is None


def test_unknown_owner_404(client):
    c, _ = client
    assert c.get("/reports/daily?owner_id=999").status_code == 404
    assert c.get("/reports/weekly?owner_id=999").status_code == 404
