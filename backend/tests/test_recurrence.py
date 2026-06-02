"""Recurring tasks — when /done fires on a task with `recurrence`, a fresh
copy is spawned with the next deadline + reset subtasks."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.services.recurrence import _add_months, _next_deadline


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", email="m@x.com"))
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


# --- unit tests on the date helpers ---

def test_next_deadline_daily():
    dl = datetime(2026, 6, 2, 17, 0, tzinfo=timezone.utc)
    assert _next_deadline(dl, "daily") == dl + timedelta(days=1)


def test_next_deadline_weekly():
    dl = datetime(2026, 6, 2, 17, 0, tzinfo=timezone.utc)
    assert _next_deadline(dl, "weekly") == dl + timedelta(days=7)


def test_next_deadline_monthly_basic():
    dl = datetime(2026, 6, 2, 17, 0, tzinfo=timezone.utc)
    assert _next_deadline(dl, "monthly") == datetime(2026, 7, 2, 17, 0, tzinfo=timezone.utc)


def test_next_deadline_monthly_clamps_jan31_to_feb28():
    # Jan 31 + 1 month: Feb only has 28 days in 2026 (not a leap year).
    dl = datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)
    assert _next_deadline(dl, "monthly") == datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)


def test_next_deadline_monthly_year_boundary():
    dl = datetime(2026, 12, 15, 9, 0, tzinfo=timezone.utc)
    assert _next_deadline(dl, "monthly") == datetime(2027, 1, 15, 9, 0, tzinfo=timezone.utc)


def test_next_deadline_none_when_no_deadline():
    assert _next_deadline(None, "daily") is None


def test_add_months_handles_year_rollover():
    assert _add_months(datetime(2026, 11, 1, tzinfo=timezone.utc), 3) == datetime(
        2027, 2, 1, tzinfo=timezone.utc,
    )


# --- /done spawns next when recurrence set ---

def test_done_on_recurring_task_spawns_next(client):
    c, SL = client
    deadline = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)

    create = c.post("/tasks", json={
        "title": "weekly review",
        "owner_id": 1,
        "deadline": deadline.isoformat(),
        "recurrence": "weekly",
    })
    assert create.status_code == 201
    task_id = create.json()["id"]
    assert create.json()["recurrence"] == "weekly"

    # Mark it done
    done = c.post(f"/tasks/{task_id}/done")
    assert done.status_code == 200

    with SL() as s:
        all_tasks = s.query(models.Task).order_by(models.Task.id).all()
        assert len(all_tasks) == 2, "should have the original + the spawned copy"
        original, spawned = all_tasks
        assert original.status == "done"
        assert spawned.status == "pending"
        assert spawned.title == "weekly review"
        assert spawned.recurrence == "weekly"
        assert spawned.owner_id == 1
        # Next deadline is original deadline + 7 days (compare normalized to UTC).
        spawned_dl = spawned.deadline if spawned.deadline.tzinfo else spawned.deadline.replace(tzinfo=timezone.utc)
        assert spawned_dl == deadline + timedelta(days=7)


def test_done_on_non_recurring_task_does_not_spawn(client):
    c, SL = client
    task_id = c.post("/tasks", json={"title": "one-shot", "owner_id": 1}).json()["id"]
    c.post(f"/tasks/{task_id}/done")
    with SL() as s:
        assert s.query(models.Task).count() == 1


def test_recurring_task_copies_subtasks_as_uncompleted(client):
    c, SL = client
    task_id = c.post("/tasks", json={
        "title": "daily standup", "owner_id": 1, "recurrence": "daily",
    }).json()["id"]
    # Add subtasks + complete some
    for i, title in enumerate(["update Slack", "review PRs", "log time"]):
        c.post(f"/tasks/{task_id}/subtasks", json={"title": title, "position": i})
    subs = c.get(f"/tasks/{task_id}/subtasks").json()
    # Tick the first as completed
    c.patch(f"/tasks/{task_id}/subtasks/{subs[0]['id']}", json={"completed": True})

    c.post(f"/tasks/{task_id}/done")

    with SL() as s:
        spawned = s.query(models.Task).filter(models.Task.id != task_id).one()
        spawned_subs = s.query(models.TaskSubtask).filter_by(task_id=spawned.id).order_by(
            models.TaskSubtask.position
        ).all()
        assert [sub.title for sub in spawned_subs] == ["update Slack", "review PRs", "log time"]
        assert all(sub.completed is False for sub in spawned_subs)


def test_patch_can_clear_recurrence_with_none_sentinel(client):
    c, _ = client
    task_id = c.post("/tasks", json={
        "title": "stop recurring", "owner_id": 1, "recurrence": "weekly",
    }).json()["id"]
    r = c.patch(f"/tasks/{task_id}", json={"recurrence": "none"})
    assert r.status_code == 200
    assert r.json()["recurrence"] is None
