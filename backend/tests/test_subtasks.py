"""Subtask CRUD + /next-action embedding tests."""

from datetime import datetime, timedelta, timezone

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
        t = models.Task(title="Edit ad video", owner_id=1, est_minutes=60, importance=8)
        s.add(t); s.flush()
        s.add(models.CalendarBlock(
            task_id=t.id, start=NOW, end=NOW + timedelta(minutes=60),
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


# ---------- CRUD ----------

def test_create_subtask_appends_at_end_when_position_omitted(client_db):
    c, _ = client_db
    r1 = c.post("/tasks/1/subtasks", json={"title": "Cut video"})
    r2 = c.post("/tasks/1/subtasks", json={"title": "Upload to YouTube"})
    r3 = c.post("/tasks/1/subtasks", json={"title": "Share link with Michael"})
    assert r1.status_code == 201 and r1.json()["position"] == 0
    assert r2.json()["position"] == 1
    assert r3.json()["position"] == 2


def test_create_subtask_with_explicit_position(client_db):
    c, _ = client_db
    r = c.post("/tasks/1/subtasks", json={"title": "First step", "position": 0})
    assert r.json()["position"] == 0


def test_create_subtask_404_on_unknown_task(client_db):
    c, _ = client_db
    r = c.post("/tasks/9999/subtasks", json={"title": "foo"})
    assert r.status_code == 404


def test_create_subtask_rejects_empty_title(client_db):
    c, _ = client_db
    r = c.post("/tasks/1/subtasks", json={"title": ""})
    assert r.status_code == 422


def test_list_subtasks_ordered_by_position(client_db):
    c, _ = client_db
    c.post("/tasks/1/subtasks", json={"title": "C", "position": 2})
    c.post("/tasks/1/subtasks", json={"title": "A", "position": 0})
    c.post("/tasks/1/subtasks", json={"title": "B", "position": 1})

    r = c.get("/tasks/1/subtasks")
    titles = [s["title"] for s in r.json()]
    assert titles == ["A", "B", "C"]


def test_toggle_completed_stamps_completed_at(client_db):
    c, SL = client_db
    sub = c.post("/tasks/1/subtasks", json={"title": "Step"}).json()
    sub_id = sub["id"]
    assert sub["completed"] is False
    assert sub["completed_at"] is None

    r = c.patch(f"/tasks/1/subtasks/{sub_id}", json={"completed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["completed"] is True
    assert body["completed_at"] is not None

    # Toggling back clears completed_at
    r = c.patch(f"/tasks/1/subtasks/{sub_id}", json={"completed": False})
    assert r.json()["completed"] is False
    assert r.json()["completed_at"] is None


def test_update_title_and_position(client_db):
    c, _ = client_db
    sub = c.post("/tasks/1/subtasks", json={"title": "Old"}).json()
    r = c.patch(f"/tasks/1/subtasks/{sub['id']}", json={"title": "New", "position": 5})
    assert r.json()["title"] == "New"
    assert r.json()["position"] == 5


def test_update_404_when_subtask_not_under_task(client_db):
    """Patching subtask under wrong task_id should 404, not silently succeed."""
    c, _ = client_db
    sub = c.post("/tasks/1/subtasks", json={"title": "Step"}).json()
    r = c.patch(f"/tasks/9999/subtasks/{sub['id']}", json={"completed": True})
    assert r.status_code == 404


def test_delete_removes_row(client_db):
    c, SL = client_db
    sub = c.post("/tasks/1/subtasks", json={"title": "Step"}).json()
    r = c.delete(f"/tasks/1/subtasks/{sub['id']}")
    assert r.status_code == 204
    with SL() as s:
        assert s.query(models.TaskSubtask).count() == 0


# ---------- /next-action embedding ----------

def test_next_action_includes_subtasks_for_current_task(client_db):
    c, _ = client_db
    c.post("/tasks/1/subtasks", json={"title": "Cut video"})
    c.post("/tasks/1/subtasks", json={"title": "Upload to YouTube"})

    r = c.get("/next-action?owner_id=1")
    body = r.json()
    assert len(body["current"]["subtasks"]) == 2
    assert body["current"]["subtasks"][0]["title"] == "Cut video"


def test_next_action_subtasks_ordered_by_position(client_db):
    c, _ = client_db
    c.post("/tasks/1/subtasks", json={"title": "Third", "position": 2})
    c.post("/tasks/1/subtasks", json={"title": "First", "position": 0})
    c.post("/tasks/1/subtasks", json={"title": "Second", "position": 1})

    r = c.get("/next-action?owner_id=1")
    titles = [s["title"] for s in r.json()["current"]["subtasks"]]
    assert titles == ["First", "Second", "Third"]
