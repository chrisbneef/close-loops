"""Reminder loop + push-token registration tests. Mocks httpx so nothing
actually hits Expo's push service during the suite."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _fake_httpx_response(json_body: dict) -> MagicMock:
    """Build a MagicMock that mimics an httpx Response well enough for our wrapper.
    Real httpx.Response.raise_for_status() needs a bound request, which is awkward to
    construct in tests; a MagicMock with raise_for_status=no-op + .json() is cleaner."""
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()  # no-op for 200 responses
    return resp
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.services import notifications, reminder_loop

VALID_TOKEN = "ExponentPushToken[abcdef1234567890]"
NOW = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)  # Mon 16:00 UTC


@pytest.fixture
def client_db():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
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
    yield TestClient(app), SessionLocal
    app.dependency_overrides.clear()


# ---------- push token validation ----------

def test_is_expo_push_token():
    assert notifications.is_expo_push_token(VALID_TOKEN)
    assert not notifications.is_expo_push_token("nope")
    assert not notifications.is_expo_push_token("")
    assert not notifications.is_expo_push_token(None)


# ---------- /users/{id}/push-token endpoint ----------

def test_set_push_token_stores_on_user(client_db):
    c, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com"))
        s.commit()

    r = c.post("/users/1/push-token", json={"push_token": VALID_TOKEN})
    assert r.status_code == 204

    with SL() as s:
        assert s.get(models.User, 1).push_token == VALID_TOKEN


def test_set_push_token_clears_with_empty_string(client_db):
    c, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com", push_token=VALID_TOKEN))
        s.commit()

    r = c.post("/users/1/push-token", json={"push_token": ""})
    assert r.status_code == 204
    with SL() as s:
        assert s.get(models.User, 1).push_token is None


def test_set_push_token_rejects_invalid_format(client_db):
    c, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com"))
        s.commit()

    r = c.post("/users/1/push-token", json={"push_token": "fcm_some_random_thing"})
    assert r.status_code == 422


def test_set_push_token_404_unknown_user(client_db):
    c, _ = client_db
    r = c.post("/users/9999/push-token", json={"push_token": VALID_TOKEN})
    assert r.status_code == 404


# ---------- notifications.send_push ----------

def test_send_push_success():
    fake = _fake_httpx_response({"data": {"status": "ok", "id": "abc"}})
    with patch("httpx.Client.post", return_value=fake):
        result = notifications.send_push(VALID_TOKEN, title="hi", body="x")
    assert result["data"]["status"] == "ok"


def test_send_push_raises_on_expo_error():
    fake = _fake_httpx_response({
        "data": {"status": "error", "message": "DeviceNotRegistered",
                 "details": {"error": "DeviceNotRegistered"}},
    })
    with patch("httpx.Client.post", return_value=fake):
        with pytest.raises(notifications.PushError):
            notifications.send_push(VALID_TOKEN, title="hi", body="x")


def test_send_push_raises_on_bad_token():
    with pytest.raises(notifications.PushError):
        notifications.send_push("not-a-token", title="hi", body="x")


# ---------- reminder_loop.tick ----------

def _seed_block(session, *, user_id: int, start_at: datetime, est_minutes: int = 25,
                title: str = "Test task", status: str = "pending",
                reminder_sent_at: datetime | None = None) -> tuple[int, int]:
    """Returns (task_id, block_id)."""
    t = models.Task(title=title, owner_id=user_id, est_minutes=est_minutes, status=status)
    session.add(t)
    session.flush()
    b = models.CalendarBlock(
        task_id=t.id, start=start_at, end=start_at + timedelta(minutes=est_minutes),
        reminder_sent_at=reminder_sent_at,
    )
    session.add(b)
    session.flush()
    session.commit()
    return t.id, b.id


def test_tick_sends_push_for_upcoming_pending_task(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com",
                          timezone="UTC", push_token=VALID_TOKEN))
        s.commit()
        _, block_id = _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=3))

    with SL() as s, patch("app.services.notifications.send_push", return_value={"data": {"status": "ok"}}) as mock_send:
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 1
        assert counts["failed"] == 0
        mock_send.assert_called_once()
        block = s.get(models.CalendarBlock, block_id)
        assert block.reminder_sent_at is not None


def test_tick_skips_blocks_outside_lead_window(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com",
                          timezone="UTC", push_token=VALID_TOKEN))
        s.commit()
        # 30 min from now — outside the default 5 min lead window
        _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=30))

    with SL() as s, patch("app.services.notifications.send_push") as mock_send:
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 0
        mock_send.assert_not_called()


def test_tick_does_not_re_send_for_already_reminded_block(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com",
                          timezone="UTC", push_token=VALID_TOKEN))
        s.commit()
        _seed_block(
            s, user_id=1, start_at=NOW + timedelta(minutes=2),
            reminder_sent_at=NOW - timedelta(minutes=1),  # already pinged
        )

    with SL() as s, patch("app.services.notifications.send_push") as mock_send:
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 0
        mock_send.assert_not_called()


def test_tick_skips_users_without_push_token(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com"))  # no push_token
        s.commit()
        _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=2))

    with SL() as s, patch("app.services.notifications.send_push") as mock_send:
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 0
        mock_send.assert_not_called()


def test_tick_skips_in_progress_and_done_tasks(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.User(name="M", role="cofounder", email="m@x.com",
                          timezone="UTC", push_token=VALID_TOKEN))
        s.commit()
        _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=2), status="in_progress")
        _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=3), status="done")

    with SL() as s, patch("app.services.notifications.send_push") as mock_send:
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 0


def test_tick_continues_after_one_push_fails(client_db):
    """One bad token shouldn't take down the whole tick."""
    _, SL = client_db
    with SL() as s:
        s.add_all([
            models.User(name="M", role="cofounder", email="m@x.com",
                        timezone="UTC", push_token=VALID_TOKEN),
            models.User(name="C", role="cofounder", email="c@x.com",
                        timezone="UTC", push_token=VALID_TOKEN),
        ])
        s.commit()
        _seed_block(s, user_id=1, start_at=NOW + timedelta(minutes=2), title="task1")
        _seed_block(s, user_id=2, start_at=NOW + timedelta(minutes=3), title="task2")

    call_count = {"n": 0}
    def fake_send(token, *, title, body, data=None, timeout_seconds=10.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise notifications.PushError("simulated network blip")
        return {"data": {"status": "ok"}}

    with SL() as s, patch("app.services.notifications.send_push", side_effect=fake_send):
        counts = reminder_loop.tick(s, now=NOW)
        assert counts["sent"] == 1
        assert counts["failed"] == 1
