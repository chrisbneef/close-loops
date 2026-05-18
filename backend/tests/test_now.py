"""Now-screen endpoint tests — covers next-action ordering, start/done state
machine, execution_log logging, and the reschedule trigger after done."""

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

NOW = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override

    with SessionLocal() as s:
        s.add_all([
            models.User(name="Michael", role="cofounder", email="m@x.com"),
            models.User(name="Chris", role="cofounder", email="c@x.com"),
        ])
        s.commit()

    yield TestClient(app), SessionLocal
    app.dependency_overrides.clear()


def _seed_scheduled(SessionLocal, owner_id: int, count: int = 3):
    """Helper: add N pending tasks for an owner with sequential calendar_blocks."""
    with SessionLocal() as s:
        tasks = []
        for i in range(count):
            t = models.Task(
                title=f"Task {i}", owner_id=owner_id, est_minutes=25, importance=8 - i,
            )
            s.add(t)
            s.flush()
            tasks.append(t)
            s.add(models.CalendarBlock(
                task_id=t.id,
                start=NOW + timedelta(minutes=30 * i),
                end=NOW + timedelta(minutes=30 * i + 25),
            ))
        s.commit()
        return [t.id for t in tasks]


def test_next_action_returns_earliest_scheduled(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=3)

    r = c.get("/next-action?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["current"]["id"] == task_ids[0]
    assert len(body["up_next"]) == 2
    assert body["up_next"][0]["id"] == task_ids[1]
    assert body["up_next"][1]["id"] == task_ids[2]
    assert body["why"] is not None


def test_next_action_returns_empty_when_no_tasks(client):
    c, _ = client
    r = c.get("/next-action?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["current"] is None
    assert body["up_next"] == []


def test_next_action_isolates_by_owner(client):
    c, SL = client
    _seed_scheduled(SL, owner_id=1, count=2)
    _seed_scheduled(SL, owner_id=2, count=1)

    r1 = c.get("/next-action?owner_id=1").json()
    r2 = c.get("/next-action?owner_id=2").json()
    assert r1["current"]["id"] != r2["current"]["id"]
    # Owner 1 has 2 tasks → 1 in up_next; owner 2 has 1 → empty up_next.
    assert len(r1["up_next"]) == 1
    assert r2["up_next"] == []


def test_next_action_skips_done_tasks(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=2)
    with SL() as s:
        s.query(models.Task).filter_by(id=task_ids[0]).update({"status": "done"})
        s.commit()

    r = c.get("/next-action?owner_id=1").json()
    assert r["current"]["id"] == task_ids[1]  # the still-pending one


def test_start_task_marks_in_progress(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=1)

    r = c.post(f"/tasks/{task_ids[0]}/start")
    assert r.status_code == 204

    with SL() as s:
        t = s.get(models.Task, task_ids[0])
        assert t.status == "in_progress"
        assert t.started_at is not None


def test_start_task_404_on_missing(client):
    c, _ = client
    r = c.post("/tasks/9999/start")
    assert r.status_code == 404


def test_start_task_409_when_already_done(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=1)
    with SL() as s:
        s.query(models.Task).filter_by(id=task_ids[0]).update({"status": "done"})
        s.commit()

    r = c.post(f"/tasks/{task_ids[0]}/start")
    assert r.status_code == 409


def test_done_after_start_logs_actual_minutes(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=2)

    # Patch reschedule so we don't hit the real scheduler (in-memory SQLite doesn't
    # have all the upstream pieces wired).
    with patch("app.routers.now.reschedule.request_reschedule_for_owner"):
        c.post(f"/tasks/{task_ids[0]}/start")
        # Simulate some time elapsed by manually backdating started_at 10 minutes.
        with SL() as s:
            t = s.get(models.Task, task_ids[0])
            t.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            s.commit()
        r = c.post(f"/tasks/{task_ids[0]}/done")

    assert r.status_code == 200
    body = r.json()
    # Response includes the new next-action.
    assert body["current"]["id"] == task_ids[1]

    with SL() as s:
        t = s.get(models.Task, task_ids[0])
        assert t.status == "done"
        assert t.finished_at is not None
        log = s.query(models.ExecutionLog).filter_by(task_id=task_ids[0]).one()
        assert 9 <= log.actual_minutes <= 11  # ~10 minutes
        assert log.estimated_minutes == 25


def test_done_without_start_falls_back_to_estimate(client):
    """Quick-finish path: user hits Done without Start (task was trivial).
    actual_minutes falls back to est_minutes so execution_log isn't garbage."""
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=1)

    with patch("app.routers.now.reschedule.request_reschedule_for_owner"):
        r = c.post(f"/tasks/{task_ids[0]}/done")
    assert r.status_code == 200

    with SL() as s:
        log = s.query(models.ExecutionLog).filter_by(task_id=task_ids[0]).one()
        assert log.actual_minutes == 25  # fell back to est_minutes


def test_done_triggers_reschedule(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=1)

    with patch("app.routers.now.reschedule.request_reschedule_for_owner") as mock_reschedule:
        c.post(f"/tasks/{task_ids[0]}/done")
        mock_reschedule.assert_called_once()
        args, kwargs = mock_reschedule.call_args
        assert args[0] == 1  # owner_id


def test_done_409_when_already_done(client):
    c, SL = client
    task_ids = _seed_scheduled(SL, owner_id=1, count=1)

    with patch("app.routers.now.reschedule.request_reschedule_for_owner"):
        c.post(f"/tasks/{task_ids[0]}/done")
        r = c.post(f"/tasks/{task_ids[0]}/done")
    assert r.status_code == 409
