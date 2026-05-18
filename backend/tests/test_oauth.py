"""OAuth route tests — verify state signing, validation, and error paths.

The actual Google token exchange is mocked; we don't hit Google's servers."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import settings
from app.db import Base, get_session
from app.main import app
from app.routers.oauth import _sign_state, _verify_state


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-client-secret")
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", email="michael@preapprovemeapp.com"))
        s.add(models.User(name="NoEmail", role="cofounder"))
        s.commit()

    def _override_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_state_signing_roundtrip():
    state = _sign_state(42, "some-nonce", "the-pkce-verifier")
    user_id, verifier = _verify_state(state)
    assert user_id == 42
    assert verifier == "the-pkce-verifier"


def test_state_signing_handles_empty_verifier():
    """Backwards-compat shape: state still valid if verifier was empty when signed."""
    state = _sign_state(42, "some-nonce")
    user_id, verifier = _verify_state(state)
    assert user_id == 42
    assert verifier == ""


def test_state_verification_rejects_tampering():
    from fastapi import HTTPException

    state = _sign_state(42, "some-nonce", "verifier")
    # Tamper with the user_id portion.
    tampered = state.replace("42:", "43:", 1)
    with pytest.raises(HTTPException) as exc:
        _verify_state(tampered)
    assert exc.value.status_code == 400
    assert "signature mismatch" in exc.value.detail.lower()


def test_state_verification_rejects_malformed():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _verify_state("not-a-valid-state")
    assert exc.value.status_code == 400


def test_start_redirects_to_google(client):
    r = client.get("/oauth/google/start?user_id=1", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]
    assert "login_hint=michael%40preapprovemeapp.com" in r.headers["location"]
    assert "access_type=offline" in r.headers["location"]


def test_start_rejects_unknown_user(client):
    r = client.get("/oauth/google/start?user_id=999", follow_redirects=False)
    assert r.status_code == 404


def test_start_rejects_user_without_email(client):
    r = client.get("/oauth/google/start?user_id=2", follow_redirects=False)
    assert r.status_code == 400
    assert "no email" in r.json()["detail"].lower()


def test_callback_stores_refresh_token(client):
    """Mock the token exchange — verify the refresh_token lands on the User row."""
    state = _sign_state(1, "nonce", "verifier")

    class FakeCreds:
        refresh_token = "ya29.fake-refresh-token"

    class FakeFlow:
        credentials = FakeCreds()
        redirect_uri = ""

        def fetch_token(self, code):
            assert code == "fake-auth-code"

    with patch("app.routers.oauth._build_flow", return_value=FakeFlow()):
        r = client.get(
            f"/oauth/google/callback?code=fake-auth-code&state={state}",
            follow_redirects=False,
        )
    assert r.status_code == 200
    assert "Connected" in r.text

    # Verify it persisted.
    from app.routers.oauth import _verify_state
    user_id, _ = _verify_state(state)
    # Pull from a fresh session via the override.
    session_gen = app.dependency_overrides[get_session]()
    session = next(session_gen)
    try:
        user = session.get(models.User, user_id)
        assert user.google_refresh_token == "ya29.fake-refresh-token"
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_callback_handles_oauth_error(client):
    r = client.get(
        "/oauth/google/callback?error=access_denied", follow_redirects=False
    )
    assert r.status_code == 400
    assert "declined" in r.text.lower()


def test_callback_rejects_bad_state(client):
    r = client.get(
        "/oauth/google/callback?code=x&state=bad:state:value", follow_redirects=False
    )
    assert r.status_code == 400


def test_callback_500s_when_no_refresh_token(client):
    """User previously authorized and Google didn't return a refresh_token."""
    state = _sign_state(1, "nonce", "verifier")

    class FakeCreds:
        refresh_token = None  # the failure mode

    class FakeFlow:
        credentials = FakeCreds()
        redirect_uri = ""

        def fetch_token(self, code):
            pass

    with patch("app.routers.oauth._build_flow", return_value=FakeFlow()):
        r = client.get(
            f"/oauth/google/callback?code=x&state={state}", follow_redirects=False
        )
    assert r.status_code == 500
    assert "myaccount.google.com/permissions" in r.json()["detail"]
