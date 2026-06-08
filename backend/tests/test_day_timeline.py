"""Day timeline + gap fill — drive the End-of-Day review flow."""

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

    # Today, anchored — 9am to 5pm.
    now = datetime.now(timezone.utc).replace(hour=17, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=9, minute=0)

    with SessionLocal() as s:
        s.add(models.User(
            name="Michael", role="cofounder", email="m@x.com", timezone="UTC",
            day_started_at=day_start,
        ))
        s.commit()

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app), SessionLocal, day_start, now
    app.dependency_overrides.clear()


# --- GET /day/timeline ---

def test_timeline_empty_returns_one_big_gap(client):
    c, _, day_start, now = client
    body = c.get("/day/timeline?owner_id=1").json()
    assert body["events"] == []
    # day_started_at→now (~8 hours) becomes a single gap.
    assert len(body["gaps"]) == 1
    assert body["gaps"][0]["duration_minutes"] >= 60


def test_timeline_detects_gap_between_two_completed_tasks(client):
    c, SL, day_start, now = client
    with SL() as s:
        # Task A: 9:00 - 10:00
        a = models.Task(title="task A", owner_id=1, status="done",
                         started_at=day_start, finished_at=day_start + timedelta(hours=1))
        s.add(a); s.flush()
        s.add(models.ExecutionLog(
            task_id=a.id, user_id=1, estimated_minutes=60, actual_minutes=60,
            started_at=day_start, finished_at=day_start + timedelta(hours=1),
        ))
        # Task B: 10:15 - 11:15
        b = models.Task(title="task B", owner_id=1, status="done",
                         started_at=day_start + timedelta(hours=1, minutes=15),
                         finished_at=day_start + timedelta(hours=2, minutes=15))
        s.add(b); s.flush()
        s.add(models.ExecutionLog(
            task_id=b.id, user_id=1, estimated_minutes=60, actual_minutes=60,
            started_at=day_start + timedelta(hours=1, minutes=15),
            finished_at=day_start + timedelta(hours=2, minutes=15),
        ))
        s.commit()

    body = c.get("/day/timeline?owner_id=1").json()
    assert len(body["events"]) == 2
    # The 10:00-10:15 gap (15 minutes).
    gaps = body["gaps"]
    fifteen_min_gaps = [g for g in gaps if g["duration_minutes"] == 15]
    assert len(fifteen_min_gaps) == 1


def test_timeline_skips_sub_5min_gaps(client):
    c, SL, day_start, now = client
    with SL() as s:
        a = models.Task(title="A", owner_id=1, status="done",
                         started_at=day_start, finished_at=day_start + timedelta(minutes=30))
        s.add(a); s.flush()
        s.add(models.ExecutionLog(
            task_id=a.id, user_id=1, estimated_minutes=30, actual_minutes=30,
            started_at=day_start, finished_at=day_start + timedelta(minutes=30),
        ))
        # 2-minute breather, then task B picks up.
        b = models.Task(title="B", owner_id=1, status="done",
                         started_at=day_start + timedelta(minutes=32),
                         finished_at=day_start + timedelta(minutes=62))
        s.add(b); s.flush()
        s.add(models.ExecutionLog(
            task_id=b.id, user_id=1, estimated_minutes=30, actual_minutes=30,
            started_at=day_start + timedelta(minutes=32),
            finished_at=day_start + timedelta(minutes=62),
        ))
        s.commit()

    body = c.get("/day/timeline?owner_id=1").json()
    tiny_gaps = [g for g in body["gaps"] if g["duration_minutes"] == 2]
    assert tiny_gaps == [], "sub-5-minute gaps shouldn't be surfaced"


def test_timeline_includes_resolved_pauses(client):
    c, SL, day_start, now = client
    with SL() as s:
        t = models.Task(title="focus", owner_id=1, status="in_progress",
                         started_at=day_start)
        s.add(t); s.flush()
        s.add(models.Interruption(
            task_id=t.id, user_id=1,
            paused_at=day_start + timedelta(hours=1),
            resumed_at=day_start + timedelta(hours=1, minutes=10),
            reason="slack ping",
        ))
        s.commit()

    body = c.get("/day/timeline?owner_id=1").json()
    pause_events = [e for e in body["events"] if e["kind"] == "pause"]
    assert len(pause_events) == 1
    assert "slack ping" in pause_events[0]["title"]


def test_timeline_clamps_to_day_started_and_day_ended(client):
    c, SL, day_start, now = client
    end = day_start + timedelta(hours=8)
    with SL() as s:
        user = s.get(models.User, 1)
        user.day_ended_at = end
        s.commit()

    body = c.get("/day/timeline?owner_id=1").json()
    assert body["day_started_at"] is not None
    assert body["day_ended_at"] is not None


# --- POST /day/gaps/fill ---

def test_fill_gap_with_task_creates_task_and_log(client):
    c, SL, day_start, now = client
    body = {
        "owner_id": 1,
        "start_at": (day_start + timedelta(hours=1)).isoformat(),
        "end_at": (day_start + timedelta(hours=1, minutes=15)).isoformat(),
        "kind": "task",
        "label": "reviewed Chris's PR",
    }
    r = c.post("/day/gaps/fill", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["kind"] == "task"
    assert "task_id" in out

    with SL() as s:
        task = s.query(models.Task).filter_by(title="reviewed Chris's PR").one()
        assert task.status == "done"
        log = s.query(models.ExecutionLog).filter_by(task_id=task.id).one()
        assert log.actual_minutes == 15


def test_fill_gap_with_pause_creates_free_standing_interruption(client):
    c, SL, day_start, now = client
    body = {
        "owner_id": 1,
        "start_at": (day_start + timedelta(hours=3)).isoformat(),
        "end_at": (day_start + timedelta(hours=4)).isoformat(),
        "kind": "pause",
        "label": "lunch",
    }
    r = c.post("/day/gaps/fill", json=body)
    assert r.status_code == 201

    with SL() as s:
        intr = s.query(models.Interruption).filter_by(reason="lunch").one()
        assert intr.task_id is None  # free-standing
        assert intr.user_id == 1


def test_fill_gap_rejects_end_before_start(client):
    c, _, day_start, _ = client
    body = {
        "owner_id": 1,
        "start_at": (day_start + timedelta(hours=2)).isoformat(),
        "end_at": (day_start + timedelta(hours=1)).isoformat(),
        "kind": "task",
        "label": "broken",
    }
    assert c.post("/day/gaps/fill", json=body).status_code == 422


def test_fill_gap_requires_label(client):
    c, _, day_start, _ = client
    body = {
        "owner_id": 1,
        "start_at": (day_start + timedelta(hours=1)).isoformat(),
        "end_at": (day_start + timedelta(hours=2)).isoformat(),
        "kind": "task",
        "label": "",
    }
    assert c.post("/day/gaps/fill", json=body).status_code == 422


def test_fill_gap_404_unknown_owner(client):
    c, _, day_start, _ = client
    body = {
        "owner_id": 9999,
        "start_at": (day_start + timedelta(hours=1)).isoformat(),
        "end_at": (day_start + timedelta(hours=2)).isoformat(),
        "kind": "pause",
        "label": "x",
    }
    assert c.post("/day/gaps/fill", json=body).status_code == 404


def test_fill_task_then_timeline_includes_it(client):
    c, _, day_start, _ = client
    c.post("/day/gaps/fill", json={
        "owner_id": 1,
        "start_at": (day_start + timedelta(hours=1)).isoformat(),
        "end_at": (day_start + timedelta(hours=2)).isoformat(),
        "kind": "task",
        "label": "client email triage",
    })
    body = c.get("/day/timeline?owner_id=1").json()
    titles = [e["title"] for e in body["events"]]
    assert "client email triage" in titles
