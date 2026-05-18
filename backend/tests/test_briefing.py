"""Briefing tests — verifies the data gather + the endpoint orchestration.
The actual Claude call is mocked; Slack POST is also mocked."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.services import briefing, slack

# A morning in UTC; users are tz="UTC" by default in fixtures so dates align.
NOW = datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc)  # Tuesday afternoon UTC


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


# ---------- briefing.gather ----------

def test_gather_pulls_yesterday_completions(client_db):
    _, SL = client_db
    yesterday_utc = NOW - timedelta(days=1)
    with SL() as s:
        t = models.Task(title="Done thing", owner_id=1, est_minutes=25, importance=8,
                        status="done", finished_at=yesterday_utc)
        s.add(t); s.flush()
        s.add(models.ExecutionLog(
            task_id=t.id, user_id=1,
            estimated_minutes=25, actual_minutes=20,
            started_at=yesterday_utc - timedelta(minutes=20), finished_at=yesterday_utc,
        ))
        s.commit()
        michael = s.get(models.User, 1)
        data = briefing.gather(s, michael, now=NOW)
    assert len(data.yesterday_completed) == 1
    assert data.yesterday_completed[0]["title"] == "Done thing"
    assert data.yesterday_completed[0]["actual_minutes"] == 20


def test_gather_pulls_today_scheduled(client_db):
    _, SL = client_db
    today_morning = NOW.replace(hour=10, minute=0)
    with SL() as s:
        t = models.Task(title="Morning task", owner_id=1, est_minutes=30, importance=9)
        s.add(t); s.flush()
        s.add(models.CalendarBlock(
            task_id=t.id, start=today_morning, end=today_morning + timedelta(minutes=30),
        ))
        s.commit()
        michael = s.get(models.User, 1)
        data = briefing.gather(s, michael, now=NOW)
    assert len(data.today_scheduled) == 1
    assert data.today_scheduled[0]["title"] == "Morning task"


def test_gather_includes_streak(client_db):
    _, SL = client_db
    with SL() as s:
        s.add(models.GamificationState(
            user_id=1, points=100, current_streak=3, longest_streak=5,
        ))
        s.commit()
        michael = s.get(models.User, 1)
        data = briefing.gather(s, michael, now=NOW)
    assert data.current_streak == 3
    assert data.longest_streak == 5


def test_gather_handles_empty_user(client_db):
    """No tasks, no log, no gamification row → graceful zeros, no crash."""
    _, SL = client_db
    with SL() as s:
        michael = s.get(models.User, 1)
        data = briefing.gather(s, michael, now=NOW)
    assert data.yesterday_completed == []
    assert data.today_scheduled == []
    assert data.current_streak == 0
    assert data.longest_streak == 0


# ---------- briefing.generate (LLM call mocked) ----------

def test_generate_returns_concatenated_text():
    data = briefing.BriefingData(
        requester_name="Test", requester_timezone="UTC", today_local="2026-05-19",
        yesterday_completed=[], today_scheduled=[], current_streak=0, longest_streak=0,
    )
    fake_client = MagicMock()
    fake_response = MagicMock(
        content=[MagicMock(type="text", text="Hello, today is good.")],
        usage=MagicMock(input_tokens=100, output_tokens=20),
    )
    fake_client.messages.create.return_value = fake_response
    text = briefing.generate(data, client=fake_client)
    assert text == "Hello, today is good."


def test_generate_filters_thinking_blocks():
    """Adaptive thinking emits thinking blocks before text — keep only text."""
    data = briefing.BriefingData(
        requester_name="Test", requester_timezone="UTC", today_local="2026-05-19",
        yesterday_completed=[], today_scheduled=[], current_streak=0, longest_streak=0,
    )
    fake_client = MagicMock()
    fake_response = MagicMock(
        content=[
            MagicMock(type="thinking", thinking="planning..."),  # should be skipped
            MagicMock(type="text", text="The real briefing."),
        ],
        usage=MagicMock(input_tokens=100, output_tokens=20),
    )
    fake_client.messages.create.return_value = fake_response
    text = briefing.generate(data, client=fake_client)
    assert text == "The real briefing."


# ---------- /briefing/today endpoint ----------

def test_endpoint_returns_briefing_and_posts_to_slack(client_db):
    c, _ = client_db
    fake_text = "You completed 3 tasks yesterday. Focus on the press launch first today."

    with patch("app.routers.briefing.briefing.generate", return_value=fake_text), \
         patch("app.routers.briefing.slack.post_message", return_value=True) as mock_slack:
        r = c.get("/briefing/today?owner_id=1&post_to_slack=true")
    assert r.status_code == 200
    body = r.json()
    assert body["briefing"] == fake_text
    assert body["posted_to_slack"] is True
    mock_slack.assert_called_once()


def test_endpoint_skips_slack_when_param_false(client_db):
    c, _ = client_db
    with patch("app.routers.briefing.briefing.generate", return_value="x"), \
         patch("app.routers.briefing.slack.post_message") as mock_slack:
        r = c.get("/briefing/today?owner_id=1&post_to_slack=false")
    assert r.status_code == 200
    assert r.json()["posted_to_slack"] is False
    mock_slack.assert_not_called()


def test_endpoint_returns_briefing_even_if_slack_fails(client_db):
    """Slack outage shouldn't lose the briefing — return it, just mark not-posted."""
    c, _ = client_db
    with patch("app.routers.briefing.briefing.generate", return_value="x"), \
         patch("app.routers.briefing.slack.post_message", side_effect=slack.SlackError("network blip")):
        r = c.get("/briefing/today?owner_id=1&post_to_slack=true")
    assert r.status_code == 200
    body = r.json()
    assert body["briefing"] == "x"
    assert body["posted_to_slack"] is False


def test_endpoint_404_on_unknown_owner(client_db):
    c, _ = client_db
    r = c.get("/briefing/today?owner_id=9999")
    assert r.status_code == 404


# ---------- slack.post_message ----------

def test_slack_no_op_when_no_url_configured():
    """Empty webhook URL → silent skip, returns False (NOT an error)."""
    assert slack.post_message("hi", webhook_url="") is False


def test_slack_returns_true_on_ok():
    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.raise_for_status = MagicMock()
    with patch("httpx.Client.post", return_value=fake_response):
        assert slack.post_message("hi", webhook_url="https://hooks.slack.com/x") is True


def test_slack_raises_on_non_ok_body():
    fake_response = MagicMock()
    fake_response.text = "invalid_payload"
    fake_response.raise_for_status = MagicMock()
    with patch("httpx.Client.post", return_value=fake_response):
        with pytest.raises(slack.SlackError):
            slack.post_message("hi", webhook_url="https://hooks.slack.com/x")
