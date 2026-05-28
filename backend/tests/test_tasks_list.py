"""GET /tasks (board listing) + PATCH /tasks/{id} (click-to-move + edits)."""

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
# GET /tasks computes its done-window cutoff from the REAL wall clock, so
# done-task timestamps in these tests must be anchored to real now (not the
# fixed sim NOW) or the window filter misbehaves when the machine clock differs.
REAL_NOW = datetime.now(timezone.utc)


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


def _task(SL, *, owner_id=1, status="pending", title="T", finished_at=None, started_at=None, subtasks=()):
    with SL() as s:
        t = models.Task(
            title=title, owner_id=owner_id, est_minutes=25, importance=5,
            status=status, finished_at=finished_at, started_at=started_at,
        )
        s.add(t); s.flush()
        for i, st in enumerate(subtasks):
            s.add(models.TaskSubtask(task_id=t.id, position=i, title=st))
        s.commit()
        return t.id


# ---------- GET /tasks ----------

def test_list_returns_all_board_statuses(client):
    c, SL = client
    _task(SL, status="pending", title="P")
    _task(SL, status="in_progress", title="IP", started_at=REAL_NOW)
    _task(SL, status="paused", title="PA")
    _task(SL, status="done", title="D", finished_at=REAL_NOW)
    body = c.get("/tasks?owner_id=1").json()
    titles = {t["title"] for t in body}
    assert titles == {"P", "IP", "PA", "D"}


def test_list_excludes_decayed(client):
    c, SL = client
    _task(SL, status="pending", title="keep")
    _task(SL, status="decayed", title="gone")
    body = c.get("/tasks?owner_id=1").json()
    assert {t["title"] for t in body} == {"keep"}


def test_list_done_window_filters_old_done(client):
    c, SL = client
    _task(SL, status="done", title="recent", finished_at=REAL_NOW - timedelta(days=1))
    _task(SL, status="done", title="old", finished_at=REAL_NOW - timedelta(days=30))
    # default window is 7 days
    body = c.get("/tasks?owner_id=1").json()
    titles = {t["title"] for t in body}
    assert "recent" in titles
    assert "old" not in titles
    # widen the window → old reappears
    body2 = c.get("/tasks?owner_id=1&done_within_days=60").json()
    assert "old" in {t["title"] for t in body2}


def test_list_embeds_subtasks(client):
    c, SL = client
    _task(SL, title="with subs", subtasks=["a", "b", "c"])
    body = c.get("/tasks?owner_id=1").json()
    task = next(t for t in body if t["title"] == "with subs")
    assert len(task["subtasks"]) == 3


def test_list_owner_isolation(client):
    c, SL = client
    _task(SL, owner_id=1, title="michael task")
    _task(SL, owner_id=2, title="chris task")
    body = c.get("/tasks?owner_id=2").json()
    assert {t["title"] for t in body} == {"chris task"}


def test_list_404_unknown_owner(client):
    c, _ = client
    assert c.get("/tasks?owner_id=9999").status_code == 404


def test_list_includes_timestamps_in_taskout(client):
    c, SL = client
    _task(SL, status="done", title="d", finished_at=REAL_NOW, started_at=REAL_NOW - timedelta(minutes=20))
    task = c.get("/tasks?owner_id=1").json()[0]
    assert task["finished_at"] is not None
    assert task["started_at"] is not None
    assert task["created_at"] is not None


# ---------- PATCH /tasks/{id} ----------

def test_patch_edits_fields(client):
    c, SL = client
    tid = _task(SL, title="old title")
    r = c.patch(f"/tasks/{tid}", json={"title": "new title", "importance": 9, "est_minutes": 45})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "new title"
    assert body["importance"] == 9
    assert body["est_minutes"] == 45


def test_patch_backward_move_clears_started_at(client):
    c, SL = client
    tid = _task(SL, status="in_progress", started_at=NOW)
    with patch_reschedule():
        r = c.patch(f"/tasks/{tid}", json={"status": "pending"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    with SL() as s:
        assert s.get(models.Task, tid).started_at is None


def test_patch_backward_move_closes_open_interruption(client):
    c, SL = client
    tid = _task(SL, status="paused", started_at=NOW)
    with SL() as s:
        s.add(models.Interruption(task_id=tid, user_id=1, paused_at=NOW, reason="x"))
        s.commit()
    with patch_reschedule():
        c.patch(f"/tasks/{tid}", json={"status": "pending"})
    with SL() as s:
        intr = s.query(models.Interruption).filter_by(task_id=tid).one()
        assert intr.resumed_at is not None


def test_patch_forward_status_rejected_409(client):
    c, SL = client
    tid = _task(SL, status="pending")
    # The schema only permits pending/scheduled, so in_progress is a 422 at the
    # schema layer — both are "rejected", which is the contract we want.
    r = c.patch(f"/tasks/{tid}", json={"status": "in_progress"})
    assert r.status_code in (409, 422)


def test_patch_404_unknown_task(client):
    c, _ = client
    assert c.patch("/tasks/9999", json={"title": "x"}).status_code == 404


# helper: patch the reschedule side-effect (it spins a real scheduler tick)
import contextlib
from unittest.mock import patch as _patch


@contextlib.contextmanager
def patch_reschedule():
    with _patch("app.routers.tasks.reschedule.request_reschedule_for_owner"):
        yield
