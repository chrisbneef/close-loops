"""Pause/resume endpoints + interruption tracking."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app

NOW = datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def client_db():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", email="m@x.com"))
        s.commit()
        t = models.Task(
            title="Focus task", owner_id=1, est_minutes=25,
            status="in_progress", started_at=NOW - timedelta(minutes=10),
        )
        s.add(t); s.flush()
        s.add(models.CalendarBlock(
            task_id=t.id, start=NOW, end=NOW + timedelta(minutes=25),
        ))
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


# ---------- /pause ----------

def test_pause_flips_status_and_creates_interruption(client_db):
    c, SL = client_db
    r = c.post("/tasks/1/pause", json={"reason": "slack ping from Chris"})
    assert r.status_code == 204
    with SL() as s:
        task = s.get(models.Task, 1)
        assert task.status == "paused"
        rows = s.query(models.Interruption).filter_by(task_id=1).all()
        assert len(rows) == 1
        assert rows[0].reason == "slack ping from Chris"
        assert rows[0].resumed_at is None
        # Presence flipped to idle
        pres = s.get(models.Presence, 1)
        assert pres is not None and pres.status == "idle"


def test_pause_requires_reason(client_db):
    c, _ = client_db
    r = c.post("/tasks/1/pause", json={"reason": ""})
    assert r.status_code == 422


def test_pause_404_unknown_task(client_db):
    c, _ = client_db
    r = c.post("/tasks/9999/pause", json={"reason": "x"})
    assert r.status_code == 404


def test_pause_409_when_not_in_progress(client_db):
    c, SL = client_db
    with SL() as s:
        s.query(models.Task).filter_by(id=1).update({"status": "pending"})
        s.commit()
    r = c.post("/tasks/1/pause", json={"reason": "x"})
    assert r.status_code == 409


# ---------- /resume ----------

def test_resume_flips_status_back_and_closes_interruption(client_db):
    c, SL = client_db
    c.post("/tasks/1/pause", json={"reason": "kid"})
    r = c.post("/tasks/1/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in_progress"

    with SL() as s:
        task = s.get(models.Task, 1)
        assert task.status == "in_progress"
        interruption = s.query(models.Interruption).filter_by(task_id=1).one()
        assert interruption.resumed_at is not None
        # Presence flipped back to focusing
        pres = s.get(models.Presence, 1)
        assert pres is not None and pres.status == "focusing"
        assert pres.current_task_id == 1


def test_resume_409_when_not_paused(client_db):
    c, _ = client_db
    # Task starts in_progress; never paused.
    r = c.post("/tasks/1/resume")
    assert r.status_code == 409


def test_pause_resume_pause_again_creates_two_interruptions(client_db):
    """Two pause cycles on the same task → two separate Interruption rows."""
    c, SL = client_db
    c.post("/tasks/1/pause", json={"reason": "first"})
    c.post("/tasks/1/resume")
    c.post("/tasks/1/pause", json={"reason": "second"})

    with SL() as s:
        rows = s.query(models.Interruption).filter_by(task_id=1).order_by(models.Interruption.paused_at).all()
        assert len(rows) == 2
        assert rows[0].reason == "first"
        assert rows[0].resumed_at is not None  # first one closed
        assert rows[1].reason == "second"
        assert rows[1].resumed_at is None      # second still open


# ---------- /next-action surfaces paused tasks ----------

def test_paused_task_still_appears_in_next_action(client_db):
    c, _ = client_db
    c.post("/tasks/1/pause", json={"reason": "interruption"})
    r = c.get("/next-action?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["current"] is not None
    assert body["current"]["id"] == 1
    assert body["current"]["status"] == "paused"


# ---------- done after pause still works ----------

def test_done_after_pause_completes_task(client_db):
    c, _ = client_db
    c.post("/tasks/1/pause", json={"reason": "interruption"})
    with patch("app.routers.now.reschedule.request_reschedule_for_owner"):
        r = c.post("/tasks/1/done")
    # /done currently requires non-done status; paused → done is allowed.
    assert r.status_code == 200
