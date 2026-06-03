"""Edit Time endpoints — GET task timing, PATCH execution_log, PATCH interruption.

These let the user fix the recorded time on a task after the fact, for when
they forgot to hit Start / Done / Resume.
"""

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

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", email="m@x.com"))
        s.flush()
        # A completed task with one execution_log row and two pauses.
        task = models.Task(title="ship the thing", owner_id=1, est_minutes=60, status="done",
                            started_at=now - timedelta(hours=2),
                            finished_at=now)
        s.add(task)
        s.flush()
        s.add(models.ExecutionLog(
            task_id=task.id, user_id=1,
            estimated_minutes=60, actual_minutes=90,
            started_at=now - timedelta(hours=2), finished_at=now,
        ))
        s.add(models.Interruption(
            task_id=task.id, user_id=1,
            paused_at=now - timedelta(hours=1, minutes=30),
            resumed_at=now - timedelta(hours=1),
            reason="slack ping",
        ))
        s.add(models.Interruption(
            task_id=task.id, user_id=1,
            paused_at=now - timedelta(minutes=30),
            resumed_at=now - timedelta(minutes=15),
            reason="coffee",
        ))
        s.commit()

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app), SessionLocal, now
    app.dependency_overrides.clear()


# --- GET /tasks/{id}/timing ---

def test_get_timing_returns_log_and_interruptions(client):
    c, _, _ = client
    r = c.get("/tasks/1/timing")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == 1
    assert body["task_status"] == "done"
    assert body["execution_log"]["actual_minutes"] == 90
    assert len(body["interruptions"]) == 2
    reasons = [i["reason"] for i in body["interruptions"]]
    assert reasons == ["slack ping", "coffee"]  # ordered by paused_at asc


def test_get_timing_404_unknown_task(client):
    c, _, _ = client
    assert c.get("/tasks/9999/timing").status_code == 404


def test_get_timing_empty_log_for_open_task(client):
    c, SL, _ = client
    with SL() as s:
        s.add(models.Task(title="not done yet", owner_id=1, status="pending"))
        s.commit()
        task_id = s.query(models.Task).filter_by(title="not done yet").one().id

    body = c.get(f"/tasks/{task_id}/timing").json()
    assert body["execution_log"] is None
    assert body["interruptions"] == []


# --- PATCH /execution-log/{id} ---

def test_patch_log_actual_minutes_directly(client):
    c, SL, _ = client
    r = c.patch("/execution-log/1", json={"actual_minutes": 45})
    assert r.status_code == 200
    assert r.json()["actual_minutes"] == 45
    with SL() as s:
        assert s.get(models.ExecutionLog, 1).actual_minutes == 45


def test_patch_log_recomputes_when_bounds_move(client):
    c, _, now = client
    new_start = (now - timedelta(hours=3)).isoformat()
    new_end = (now - timedelta(hours=1)).isoformat()
    r = c.patch("/execution-log/1", json={
        "started_at": new_start, "finished_at": new_end,
    })
    assert r.status_code == 200
    # 2-hour delta = 120 minutes
    assert r.json()["actual_minutes"] == 120


def test_patch_log_explicit_minutes_wins_over_bounds(client):
    c, _, now = client
    r = c.patch("/execution-log/1", json={
        "started_at": (now - timedelta(hours=5)).isoformat(),
        "actual_minutes": 25,
    })
    assert r.json()["actual_minutes"] == 25


def test_patch_log_can_edit_completion_notes(client):
    c, _, _ = client
    r = c.patch("/execution-log/1", json={"completion_notes": "Drive: https://x"})
    assert r.json()["completion_notes"] == "Drive: https://x"


def test_patch_log_404_unknown_id(client):
    c, _, _ = client
    assert c.patch("/execution-log/9999", json={"actual_minutes": 10}).status_code == 404


def test_patch_log_validates_actual_minutes_range(client):
    c, _, _ = client
    assert c.patch("/execution-log/1", json={"actual_minutes": -5}).status_code == 422
    assert c.patch("/execution-log/1", json={"actual_minutes": 99999}).status_code == 422


# --- PATCH /interruptions/{id} ---

def test_patch_interruption_paused_and_resumed(client):
    c, _, now = client
    new_paused = (now - timedelta(hours=1)).isoformat()
    new_resumed = (now - timedelta(minutes=50)).isoformat()
    r = c.patch("/interruptions/1", json={
        "paused_at": new_paused, "resumed_at": new_resumed,
    })
    assert r.status_code == 200
    assert r.json()["paused_at"].startswith(new_paused[:19])


def test_patch_interruption_reason(client):
    c, _, _ = client
    r = c.patch("/interruptions/1", json={"reason": "family phone call"})
    assert r.json()["reason"] == "family phone call"


def test_patch_interruption_404_unknown_id(client):
    c, _, _ = client
    assert c.patch("/interruptions/9999", json={"reason": "x"}).status_code == 404


def test_patch_interruption_validates_reason_length(client):
    c, _, _ = client
    assert c.patch("/interruptions/1", json={"reason": ""}).status_code == 422
