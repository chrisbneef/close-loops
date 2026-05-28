"""Weekly report endpoint tests — covers the on-time/late/over-est math,
date-window filtering, owner isolation, and the longest-overrun pick."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app

# Anchored to real now (not a fixed calendar date): the /reports/weekly default
# window is [now-7d, now] off the real clock, so a hardcoded past date silently
# falls out of the window once the machine clock advances past it.
NOW = datetime.now(timezone.utc)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add_all([
            models.User(name="Michael", role="cofounder", email="m@x.com"),
            models.User(name="Chris", role="cofounder", email="c@x.com"),
        ])
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


def _seed_completion(
    SessionLocal, *, owner_id: int, est: int, actual: int,
    importance: int = 5, deadline: datetime | None = None,
    finished_at: datetime | None = None, title: str = "T",
    scheduled_for: datetime | None = None,
):
    """Insert a Task + matching ExecutionLog row representing a completed task."""
    finished_at = finished_at or NOW
    with SessionLocal() as s:
        t = models.Task(
            title=title, owner_id=owner_id, est_minutes=est, importance=importance,
            deadline=deadline, status="done", finished_at=finished_at,
        )
        s.add(t)
        s.flush()
        s.add(models.ExecutionLog(
            task_id=t.id, user_id=owner_id,
            estimated_minutes=est, actual_minutes=actual,
            started_at=finished_at - timedelta(minutes=actual),
            finished_at=finished_at,
            scheduled_for=scheduled_for,
        ))
        s.commit()
        return t.id


# ---------- empty + 404 paths ----------

def test_empty_report_returns_zeros(client):
    c, _ = client
    r = c.get("/reports/weekly?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total_completed"] == 0
    assert body["completed_on_time"] == 0
    assert body["completed_late"] == 0
    assert body["avg_actual_over_est"] is None
    assert body["rows"] == []
    assert body["longest_overrun"] is None


def test_unknown_owner_404(client):
    c, _ = client
    r = c.get("/reports/weekly?owner_id=9999")
    assert r.status_code == 404


# ---------- on-time / late / no-deadline classification ----------

def test_on_time_when_finished_before_deadline(client):
    c, SL = client
    _seed_completion(
        SL, owner_id=1, est=25, actual=20,
        deadline=NOW + timedelta(hours=2),  # finished NOW, deadline is 2h later
        finished_at=NOW,
    )
    body = c.get("/reports/weekly?owner_id=1").json()
    assert body["completed_on_time"] == 1
    assert body["completed_late"] == 0
    assert body["rows"][0]["on_time"] is True


def test_late_when_finished_after_deadline(client):
    c, SL = client
    _seed_completion(
        SL, owner_id=1, est=25, actual=30,
        deadline=NOW - timedelta(hours=2),  # deadline already past
        finished_at=NOW,
    )
    body = c.get("/reports/weekly?owner_id=1").json()
    assert body["completed_late"] == 1
    assert body["completed_on_time"] == 0
    assert body["rows"][0]["on_time"] is False


def test_no_deadline_counted_separately(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=20, deadline=None, finished_at=NOW)
    body = c.get("/reports/weekly?owner_id=1").json()
    assert body["no_deadline"] == 1
    assert body["completed_on_time"] == 0
    assert body["completed_late"] == 0
    assert body["rows"][0]["on_time"] is None


# ---------- ratio math + totals ----------

def test_avg_actual_over_est_is_correct(client):
    c, SL = client
    # 3 tasks: 1x, 2x, 1.5x. Avg = 1.5.
    _seed_completion(SL, owner_id=1, est=20, actual=20, finished_at=NOW - timedelta(hours=3))
    _seed_completion(SL, owner_id=1, est=20, actual=40, finished_at=NOW - timedelta(hours=2))
    _seed_completion(SL, owner_id=1, est=20, actual=30, finished_at=NOW - timedelta(hours=1))

    body = c.get("/reports/weekly?owner_id=1").json()
    assert body["total_completed"] == 3
    assert body["avg_actual_over_est"] == 1.5
    assert body["total_minutes_estimated"] == 60
    assert body["total_minutes_actual"] == 90


# ---------- longest overrun selection ----------

def test_longest_overrun_picks_max_delta(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=30, title="small overrun", finished_at=NOW - timedelta(hours=2))
    big_id = _seed_completion(SL, owner_id=1, est=20, actual=120, title="big overrun", finished_at=NOW - timedelta(hours=1))
    _seed_completion(SL, owner_id=1, est=30, actual=10, title="under estimate", finished_at=NOW)

    body = c.get("/reports/weekly?owner_id=1").json()
    assert body["longest_overrun"]["task_id"] == big_id
    assert body["longest_overrun"]["title"] == "big overrun"


# ---------- by_importance bucketing ----------

def test_by_importance_groups_counts(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=20, importance=10,
                     deadline=NOW + timedelta(hours=1), finished_at=NOW)
    _seed_completion(SL, owner_id=1, est=25, actual=30, importance=10,
                     deadline=NOW - timedelta(hours=1), finished_at=NOW)
    _seed_completion(SL, owner_id=1, est=25, actual=20, importance=3,
                     deadline=NOW + timedelta(hours=1), finished_at=NOW)

    body = c.get("/reports/weekly?owner_id=1").json()
    # JSON dict keys come back as strings.
    assert body["by_importance"]["10"] == {"completed": 2, "on_time": 1, "late": 1}
    assert body["by_importance"]["3"] == {"completed": 1, "on_time": 1, "late": 0}


# ---------- date window filtering ----------

def test_old_completions_excluded_from_window(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=20, finished_at=NOW - timedelta(days=30))
    _seed_completion(SL, owner_id=1, est=25, actual=20, finished_at=NOW)

    r = c.get("/reports/weekly", params={
        "owner_id": 1, "end_date": NOW.isoformat(), "window_days": 7,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_completed"] == 1  # the 30-day-old one is filtered out


def test_window_days_param_widens_range(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=20, finished_at=NOW - timedelta(days=20))
    _seed_completion(SL, owner_id=1, est=25, actual=20, finished_at=NOW)

    r = c.get("/reports/weekly", params={
        "owner_id": 1, "end_date": NOW.isoformat(), "window_days": 30,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_completed"] == 2


# ---------- owner isolation ----------

def test_owner_isolation(client):
    c, SL = client
    _seed_completion(SL, owner_id=1, est=25, actual=20)
    _seed_completion(SL, owner_id=2, est=25, actual=20)
    _seed_completion(SL, owner_id=2, est=25, actual=20)

    r1 = c.get("/reports/weekly?owner_id=1").json()
    r2 = c.get("/reports/weekly?owner_id=2").json()
    assert r1["total_completed"] == 1
    assert r2["total_completed"] == 2


# ---------- scheduled_for surfaced in report rows ----------

def test_scheduled_for_appears_in_report_row(client):
    c, SL = client
    scheduled = NOW - timedelta(days=2)  # was scheduled 2 days before completion
    _seed_completion(
        SL, owner_id=1, est=25, actual=20, scheduled_for=scheduled, finished_at=NOW,
    )
    body = c.get("/reports/weekly?owner_id=1").json()
    row = body["rows"][0]
    assert row["scheduled_for"] is not None
