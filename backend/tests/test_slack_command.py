"""Slack slash-command intake — signature verification, ack behavior, and the
background decomposition worker."""

import hashlib
import hmac
import time
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.services import slack as slack_service

SIGNING_SECRET = "test-signing-secret"


def _sign(body: str, secret: str = SIGNING_SECRET, ts: str | None = None):
    ts = ts or str(int(time.time()))
    base = f"v0:{ts}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return ts, sig


# ---------- signature verification (unit) ----------

def test_verify_signature_accepts_valid():
    body = b"command=%2Floop&text=hi"
    ts, sig = _sign(body.decode())
    assert slack_service.verify_slack_signature(
        request_body=body, timestamp=ts, signature=sig, signing_secret=SIGNING_SECRET
    )


def test_verify_signature_rejects_tampered_body():
    ts, sig = _sign("command=%2Floop&text=hi")
    assert not slack_service.verify_slack_signature(
        request_body=b"command=%2Floop&text=TAMPERED", timestamp=ts, signature=sig,
        signing_secret=SIGNING_SECRET,
    )


def test_verify_signature_rejects_old_timestamp():
    old_ts = str(int(time.time()) - 10_000)
    ts, sig = _sign("x", ts=old_ts)
    assert not slack_service.verify_slack_signature(
        request_body=b"x", timestamp=old_ts, signature=sig, signing_secret=SIGNING_SECRET
    )


def test_verify_signature_no_secret_returns_false():
    assert not slack_service.verify_slack_signature(
        request_body=b"x", timestamp=str(int(time.time())), signature="v0=whatever",
        signing_secret="",
    )


# ---------- endpoint ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.routers.slack.settings.slack_signing_secret", SIGNING_SECRET)

    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add_all([
            models.User(name="Michael", role="cofounder", email="m@x.com", slack_user_id="U_MICHAEL"),
            models.User(name="Chris", role="cofounder", email="c@x.com", slack_user_id="U_CHRIS"),
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


def _post(c, text: str, user_id: str = "U_MICHAEL"):
    body = urlencode({
        "command": "/loop", "text": text, "user_id": user_id,
        "response_url": "https://hooks.slack.test/response",
    })
    ts, sig = _sign(body)
    return c.post(
        "/slack/command",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )


def test_command_rejects_bad_signature(client):
    c, _ = client
    body = urlencode({"command": "/loop", "text": "hi"})
    r = c.post(
        "/slack/command", content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=deadbeef",
        },
    )
    assert r.status_code == 200
    assert "verification failed" in r.json()["text"].lower()


def test_command_empty_text_returns_usage(client):
    c, _ = client
    r = _post(c, "")
    assert r.status_code == 200
    assert "usage" in r.json()["text"].lower()


def test_command_acks_immediately_and_schedules_work(client):
    c, _ = client
    # Patch the background worker so we just assert it was scheduled, not run.
    with patch("app.routers.slack._process_goal") as mock_worker:
        r = _post(c, "I need Chris to edit the launch video by Friday")
    assert r.status_code == 200
    assert "breaking down" in r.json()["text"].lower()
    # FastAPI runs background tasks after the response in TestClient, so the
    # mock should have been called once the request completed.
    mock_worker.assert_called_once()
    args = mock_worker.call_args.args
    assert args[0] == "I need Chris to edit the launch video by Friday"
    assert args[1] == "U_MICHAEL"


# ---------- background worker (direct) ----------

def test_process_goal_resolves_requester_and_ingests(client):
    c, SL = client
    from app.routers import slack as slack_router
    from app.schemas import LLMDecomposition, LLMTask

    fake = LLMDecomposition(
        reasoning="stub decomposition for the slack test path",
        tasks=[
            LLMTask(title="Cut the launch video to 90 seconds", est_minutes=45,
                    importance=8, suggested_owner="partner",
                    subtasks=["Import footage", "Cut to 90s", "Export 1080p"]),
        ],
    )

    # Patch the LLM call inside the ingest pipeline + reschedule (would hit the
    # real Postgres via its own SessionLocal) + the slack post-back.
    with patch("app.services.decomposition.llm.decompose", return_value=fake), \
         patch("app.services.decomposition.reschedule.request_reschedule_for_owner"), \
         patch("app.routers.slack.slack.post_to_response_url") as mock_post, \
         patch("app.routers.slack.SessionLocal", SL):
        slack_router._process_goal(
            "I need Chris to edit the launch video by Friday",
            "U_MICHAEL", "https://hooks.slack.test/response",
        )

    # Confirmation posted to Slack
    mock_post.assert_called_once()
    posted_text = mock_post.call_args.args[1]
    assert "Cut the launch video" in posted_text

    # Task persisted + routed to Chris (partner), with subtasks
    with SL() as s:
        chris = s.query(models.User).filter_by(name="Chris").one()
        task = s.query(models.Task).filter_by(owner_id=chris.id).one()
        assert task.title == "Cut the launch video to 90 seconds"
        subs = s.query(models.TaskSubtask).filter_by(task_id=task.id).all()
        assert len(subs) == 3
