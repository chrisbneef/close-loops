"""Manual task creation (the widget +task button)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app

NOW = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Chris", role="cofounder", email="c@x.com"))
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


def test_create_task_returns_201_and_persists(client):
    c, SL = client
    r = c.post("/tasks", json={"title": "Call the bank", "owner_id": 1})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Call the bank"
    assert body["status"] == "pending"
    assert body["est_minutes"] == 25  # default
    assert body["importance"] == 5    # default

    with SL() as s:
        assert s.query(models.Task).count() == 1


def test_create_task_appends_locked_block_so_it_surfaces(client):
    c, SL = client
    r = c.post("/tasks", json={"title": "Quick task", "owner_id": 1, "est_minutes": 15})
    task_id = r.json()["id"]

    with SL() as s:
        block = s.query(models.CalendarBlock).filter_by(task_id=task_id).one()
        assert block.locked is True
        # 15-minute block
        assert (block.end - block.start) == timedelta(minutes=15)

    # And it shows up in /next-action
    na = c.get("/next-action?owner_id=1").json()
    assert na["current"] is not None
    assert na["current"]["id"] == task_id


def test_create_task_appends_after_existing_blocks(client):
    c, SL = client
    # Seed an existing block far in the future.
    with SL() as s:
        existing = models.Task(title="existing", owner_id=1, est_minutes=30)
        s.add(existing); s.flush()
        future_start = NOW + timedelta(days=2)
        s.add(models.CalendarBlock(
            task_id=existing.id, start=future_start, end=future_start + timedelta(minutes=30),
        ))
        s.commit()
        future_end = future_start + timedelta(minutes=30)

    r = c.post("/tasks", json={"title": "New task", "owner_id": 1, "est_minutes": 20})
    new_id = r.json()["id"]
    with SL() as s:
        new_block = s.query(models.CalendarBlock).filter_by(task_id=new_id).one()
        # Should start at/after the existing block's end (appended, not overlapping).
        assert new_block.start.replace(tzinfo=timezone.utc) >= future_end


def test_create_task_404_unknown_owner(client):
    c, _ = client
    r = c.post("/tasks", json={"title": "x", "owner_id": 9999})
    assert r.status_code == 404


def test_create_task_validates_title(client):
    c, _ = client
    r = c.post("/tasks", json={"title": "", "owner_id": 1})
    assert r.status_code == 422


def test_create_task_accepts_importance_and_deadline(client):
    c, _ = client
    deadline = (NOW + timedelta(days=3)).isoformat()
    r = c.post("/tasks", json={
        "title": "Important thing", "owner_id": 1,
        "importance": 9, "est_minutes": 45, "deadline": deadline,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["importance"] == 9
    assert body["est_minutes"] == 45
    assert body["deadline"] is not None
