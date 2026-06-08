"""Day Plan endpoints — GET /day-plan + POST /day/start."""

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


def _make_task_with_block(s, *, title, start, end, owner_id=1, status="pending"):
    t = models.Task(title=title, owner_id=owner_id, status=status, est_minutes=60)
    s.add(t); s.flush()
    s.add(models.CalendarBlock(task_id=t.id, start=start, end=end, locked=True))
    return t


# --- GET /day-plan ---

def test_day_plan_404_unknown_owner(client):
    c, _ = client
    assert c.get("/day-plan?owner_id=9999").status_code == 404


def test_day_plan_returns_today_blocks_only(client):
    c, SL = client
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today_9 = now.replace(hour=9, minute=0, second=0)
    yesterday_9 = today_9 - timedelta(days=1)
    tomorrow_9 = today_9 + timedelta(days=1)
    with SL() as s:
        _make_task_with_block(s, title="today task", start=today_9, end=today_9 + timedelta(hours=1))
        _make_task_with_block(s, title="yesterday task", start=yesterday_9, end=yesterday_9 + timedelta(hours=1))
        _make_task_with_block(s, title="tomorrow task", start=tomorrow_9, end=tomorrow_9 + timedelta(hours=1))
        s.commit()

    body = c.get("/day-plan?owner_id=1").json()
    titles = [i["title"] for i in body["items"]]
    assert titles == ["today task"]
    assert body["items"][0]["type"] == "task"
    assert body["items"][0]["task_id"] is not None


def test_day_plan_empty_when_no_blocks_today(client):
    c, _ = client
    body = c.get("/day-plan?owner_id=1").json()
    assert body["items"] == []
    assert body["has_started"] is False


def test_day_plan_has_started_false_for_yesterday(client):
    c, SL = client
    with SL() as s:
        user = s.get(models.User, 1)
        user.day_started_at = datetime.now(timezone.utc) - timedelta(days=2)
        s.commit()

    body = c.get("/day-plan?owner_id=1").json()
    assert body["has_started"] is False


def test_day_plan_has_started_true_when_set_today(client):
    c, SL = client
    with SL() as s:
        user = s.get(models.User, 1)
        user.day_started_at = datetime.now(timezone.utc)
        s.commit()

    body = c.get("/day-plan?owner_id=1").json()
    assert body["has_started"] is True


def test_day_plan_returns_owner_local_date_in_iso(client):
    c, _ = client
    body = c.get("/day-plan?owner_id=1").json()
    # Default tz is UTC; just check the ISO shape.
    assert len(body["date"]) == 10
    assert body["date"][4] == "-"
    assert body["date"][7] == "-"


# --- POST /day/start ---

def test_start_day_404_unknown_owner(client):
    c, _ = client
    assert c.post("/day/start?owner_id=9999").status_code == 404


def test_start_day_marks_day_started_and_returns_plan(client):
    c, SL = client
    r = c.post("/day/start?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["has_started"] is True
    assert body["owner_id"] == 1

    with SL() as s:
        user = s.get(models.User, 1)
        assert user.day_started_at is not None


def test_start_day_then_day_plan_shows_has_started(client):
    c, _ = client
    c.post("/day/start?owner_id=1")
    body = c.get("/day-plan?owner_id=1").json()
    assert body["has_started"] is True
