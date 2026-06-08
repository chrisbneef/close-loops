"""Time-card extensions: edit started_at on tasks, manually add interruptions
(retroactive pause punches), End Your Day."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app


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


# --- PATCH /tasks/{id} with started_at (backdate the start punch) ---

def test_patch_task_started_at_for_in_progress(client):
    c, SL = client
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SL() as s:
        s.add(models.Task(title="ship it", owner_id=1, status="in_progress", started_at=now))
        s.commit()
        task_id = s.query(models.Task).one().id

    new_start = (now - timedelta(hours=2)).isoformat()
    r = c.patch(f"/tasks/{task_id}", json={"started_at": new_start})
    assert r.status_code == 200
    with SL() as s:
        task = s.get(models.Task, task_id)
        # SQLite drops tzinfo; normalize for compare.
        start = task.started_at if task.started_at.tzinfo else task.started_at.replace(tzinfo=timezone.utc)
        assert start == now - timedelta(hours=2)


# --- POST /tasks/{id}/interruptions (manually add a pause) ---

def test_add_interruption_with_resumed_at(client):
    c, SL = client
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SL() as s:
        s.add(models.Task(title="focus", owner_id=1, status="in_progress", started_at=now))
        s.commit()
        task_id = s.query(models.Task).one().id

    body = {
        "paused_at": (now - timedelta(hours=1)).isoformat(),
        "resumed_at": (now - timedelta(minutes=30)).isoformat(),
        "reason": "coffee",
    }
    r = c.post(f"/tasks/{task_id}/interruptions", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["reason"] == "coffee"
    assert out["resumed_at"] is not None

    with SL() as s:
        assert s.query(models.Interruption).filter_by(task_id=task_id).count() == 1


def test_add_interruption_open_ended_for_still_paused(client):
    c, SL = client
    with SL() as s:
        s.add(models.Task(title="x", owner_id=1, status="paused"))
        s.commit()
        task_id = s.query(models.Task).one().id

    body = {
        "paused_at": "2026-06-03T11:30:00+00:00",
        "reason": "long meeting",
    }
    r = c.post(f"/tasks/{task_id}/interruptions", json=body)
    assert r.status_code == 201
    assert r.json()["resumed_at"] is None


def test_add_interruption_404_unknown_task(client):
    c, _ = client
    r = c.post("/tasks/9999/interruptions", json={
        "paused_at": "2026-06-03T11:30:00+00:00", "reason": "x",
    })
    assert r.status_code == 404


def test_add_interruption_rejects_resumed_before_paused(client):
    c, SL = client
    with SL() as s:
        s.add(models.Task(title="x", owner_id=1)); s.commit()
        task_id = s.query(models.Task).one().id

    body = {
        "paused_at": "2026-06-03T12:00:00+00:00",
        "resumed_at": "2026-06-03T11:30:00+00:00",
        "reason": "broken",
    }
    assert c.post(f"/tasks/{task_id}/interruptions", json=body).status_code == 422


def test_add_interruption_requires_reason(client):
    c, SL = client
    with SL() as s:
        s.add(models.Task(title="x", owner_id=1)); s.commit()
        task_id = s.query(models.Task).one().id

    body = {"paused_at": "2026-06-03T11:30:00+00:00", "reason": ""}
    assert c.post(f"/tasks/{task_id}/interruptions", json=body).status_code == 422


# --- POST /day/end ---

def test_end_day_marks_day_ended_and_returns_plan(client):
    c, SL = client
    r = c.post("/day/end?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["has_ended"] is True

    with SL() as s:
        user = s.get(models.User, 1)
        assert user.day_ended_at is not None


def test_end_day_404_unknown_owner(client):
    c, _ = client
    assert c.post("/day/end?owner_id=9999").status_code == 404


def test_day_plan_reflects_has_ended(client):
    c, _ = client
    body_before = c.get("/day-plan?owner_id=1").json()
    assert body_before["has_ended"] is False

    c.post("/day/end?owner_id=1")
    body_after = c.get("/day-plan?owner_id=1").json()
    assert body_after["has_ended"] is True
