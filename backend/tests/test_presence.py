"""Presence + body-doubling tests.

Covers: heartbeat upsert, partner lookup, the auto-stale logic (offline if
updated_at > 5 min), task title resolution for the focusing state, and the
implicit presence updates from /tasks/{id}/start and /done."""

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
from app.services import presence

NOW = datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def client_db():
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


# ---------- presence.update_presence ----------

def test_update_presence_upserts(session, cofounders):
    michael, _ = cofounders
    presence.update_presence(session, michael.id, status="focusing", current_task_id=42)
    session.commit()
    row = session.get(models.Presence, michael.id)
    assert row.status == "focusing"
    assert row.current_task_id == 42

    presence.update_presence(session, michael.id, status="idle", current_task_id=None)
    session.commit()
    row = session.get(models.Presence, michael.id)
    assert row.status == "idle"
    assert row.current_task_id is None


def test_update_presence_rejects_invalid_status(session, cofounders):
    michael, _ = cofounders
    with pytest.raises(ValueError):
        presence.update_presence(session, michael.id, status="bogus")


# ---------- partner lookup ----------

def test_find_partner_returns_other_cofounder(session, cofounders):
    michael, chris = cofounders
    assert presence.find_partner(session, michael.id).id == chris.id
    assert presence.find_partner(session, chris.id).id == michael.id


def test_find_partner_none_when_solo(session):
    s_user = models.User(name="Solo", role="cofounder", email="s@x.com")
    session.add(s_user)
    session.commit()
    assert presence.find_partner(session, s_user.id) is None


# ---------- staleness ----------

def test_get_effective_presence_returns_offline_when_stale(session, cofounders):
    michael, _ = cofounders
    presence.update_presence(session, michael.id, status="focusing", current_task_id=1)
    session.commit()
    # Force the row's updated_at into the past by 30 minutes.
    row = session.get(models.Presence, michael.id)
    row.updated_at = NOW - timedelta(minutes=30)
    session.commit()

    eff = presence.get_effective_presence(session, michael.id, now=NOW)
    assert eff.status == "offline"
    assert eff.current_task_id is None
    # Stored row is NOT mutated — only the returned (detached) copy is.
    stored = session.get(models.Presence, michael.id)
    assert stored.status == "focusing"


def test_get_effective_presence_returns_real_status_when_fresh(session, cofounders):
    michael, _ = cofounders
    presence.update_presence(session, michael.id, status="focusing", current_task_id=1)
    session.commit()
    row = session.get(models.Presence, michael.id)
    row.updated_at = NOW - timedelta(minutes=2)  # within 5-min window
    session.commit()

    eff = presence.get_effective_presence(session, michael.id, now=NOW)
    assert eff.status == "focusing"
    assert eff.current_task_id == 1


# ---------- endpoints ----------

def test_heartbeat_endpoint_updates_presence(client_db):
    c, SL = client_db
    r = c.post("/presence/heartbeat?owner_id=1", json={"status": "focusing", "current_task_id": 42})
    assert r.status_code == 204
    with SL() as s:
        row = s.get(models.Presence, 1)
        assert row.status == "focusing"
        assert row.current_task_id == 42


def test_heartbeat_rejects_invalid_status(client_db):
    c, _ = client_db
    r = c.post("/presence/heartbeat?owner_id=1", json={"status": "bogus"})
    assert r.status_code == 422


def test_heartbeat_404_on_unknown_owner(client_db):
    c, _ = client_db
    r = c.post("/presence/heartbeat?owner_id=9999", json={"status": "focusing"})
    assert r.status_code == 404


def test_partner_endpoint_returns_other_cofounders_presence(client_db):
    c, SL = client_db
    # Chris is focusing on task 7
    with SL() as s:
        t = models.Task(title="Refactor auth", owner_id=2, est_minutes=25)
        s.add(t); s.flush()
        s.add(models.Presence(user_id=2, status="focusing", current_task_id=t.id))
        s.commit()

    r = c.get("/presence/partner?owner_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["user_name"] == "Chris"
    assert body["status"] == "focusing"
    assert body["current_task_title"] == "Refactor auth"


def test_partner_endpoint_returns_null_for_solo_team(client_db):
    c, SL = client_db
    with SL() as s:
        # Promote Chris to non-cofounder so Michael is "alone".
        chris = s.get(models.User, 2)
        chris.role = "team"
        s.commit()

    r = c.get("/presence/partner?owner_id=1")
    assert r.status_code == 200
    assert r.json() is None


def test_partner_endpoint_returns_null_if_partner_never_online(client_db):
    c, _ = client_db
    r = c.get("/presence/partner?owner_id=1")  # Chris has no presence row
    assert r.status_code == 200
    assert r.json() is None


# ---------- implicit presence updates from /start and /done ----------

def test_start_endpoint_sets_focusing(client_db):
    c, SL = client_db
    with SL() as s:
        t = models.Task(title="Work", owner_id=1, est_minutes=25)
        s.add(t); s.flush()
        s.add(models.CalendarBlock(task_id=t.id, start=NOW, end=NOW + timedelta(minutes=25)))
        s.commit()
        task_id = t.id

    c.post(f"/tasks/{task_id}/start")
    with SL() as s:
        row = s.get(models.Presence, 1)
        assert row.status == "focusing"
        assert row.current_task_id == task_id


def test_done_endpoint_sets_idle(client_db):
    c, SL = client_db
    with SL() as s:
        t = models.Task(title="Work", owner_id=1, est_minutes=25)
        s.add(t); s.flush()
        s.add(models.CalendarBlock(task_id=t.id, start=NOW, end=NOW + timedelta(minutes=25)))
        s.commit()
        task_id = t.id

    with patch("app.routers.now.reschedule.request_reschedule_for_owner"):
        c.post(f"/tasks/{task_id}/start")
        c.post(f"/tasks/{task_id}/done")
    with SL() as s:
        row = s.get(models.Presence, 1)
        assert row.status == "idle"
        assert row.current_task_id is None
