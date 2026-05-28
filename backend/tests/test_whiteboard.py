"""White Board column (parked-idea backlog status).

Covers: creating directly into whiteboard (no calendar block, doesn't surface
as next-action), the board list including whiteboard, parking a scheduled task
(unlocks + drops its block on reschedule), and promoting back to pending.
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

NOW = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)


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


def test_create_into_whiteboard_has_no_block_and_does_not_surface(client):
    c, SL = client
    r = c.post("/tasks", json={"title": "Maybe a podcast?", "owner_id": 1, "status": "whiteboard"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "whiteboard"
    task_id = body["id"]

    # No calendar block was created for a parked idea.
    with SL() as s:
        assert s.query(models.CalendarBlock).filter_by(task_id=task_id).count() == 0

    # And it does NOT show up as the next action.
    na = c.get("/next-action?owner_id=1").json()
    assert na["current"] is None


def test_default_create_status_is_pending_with_block(client):
    c, SL = client
    r = c.post("/tasks", json={"title": "Do the thing", "owner_id": 1})
    assert r.json()["status"] == "pending"
    with SL() as s:
        assert s.query(models.CalendarBlock).filter_by(task_id=r.json()["id"]).count() == 1


def test_board_list_includes_whiteboard(client):
    c, _ = client
    c.post("/tasks", json={"title": "idea", "owner_id": 1, "status": "whiteboard"})
    c.post("/tasks", json={"title": "committed", "owner_id": 1})
    rows = c.get("/tasks?owner_id=1").json()
    statuses = {t["status"] for t in rows}
    assert "whiteboard" in statuses
    assert "pending" in statuses


def test_park_pending_task_to_whiteboard_unlocks_its_block(client):
    c, SL = client
    task_id = c.post("/tasks", json={"title": "committed", "owner_id": 1}).json()["id"]
    # It starts with a LOCKED block.
    with SL() as s:
        block = s.query(models.CalendarBlock).filter_by(task_id=task_id).one()
        assert block.locked is True

    r = c.patch(f"/tasks/{task_id}", json={"status": "whiteboard"})
    assert r.status_code == 200
    assert r.json()["status"] == "whiteboard"

    # patch_task unlocks the block so the subsequent reschedule's diff will drop
    # it (incl. the Google event) — parked ideas have no calendar presence.
    # (The reschedule itself runs on a separate session, so here we assert the
    # unlock; persistence tests cover the actual deletion of inactive-task blocks.)
    with SL() as s:
        block = s.query(models.CalendarBlock).filter_by(task_id=task_id).one()
        assert block.locked is False


def test_promote_whiteboard_to_pending(client):
    c, _ = client
    task_id = c.post("/tasks", json={"title": "idea", "owner_id": 1, "status": "whiteboard"}).json()["id"]
    r = c.patch(f"/tasks/{task_id}", json={"status": "pending"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_forward_move_still_rejected(client):
    c, _ = client
    task_id = c.post("/tasks", json={"title": "idea", "owner_id": 1, "status": "whiteboard"}).json()["id"]
    r = c.patch(f"/tasks/{task_id}", json={"status": "done"})
    assert r.status_code == 422  # Literal rejects 'done' before reaching the handler
