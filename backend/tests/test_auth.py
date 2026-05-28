"""Auth (Phase 8): login, /auth/me, and that protected routers reject anonymous
calls. Marked real_auth so the conftest bypass doesn't apply — these exercise
the genuine JWT + 401 path."""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.services import auth as auth_service

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(
            name="Chris", role="cofounder", email="chris@example.com",
            password_hash=auth_service.hash_password("hunter2"),
        ))
        s.add(models.User(name="NoLogin", role="contractor", email="np@example.com"))
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


def _token(client) -> str:
    c, _ = client
    r = c.post("/auth/login", json={"email": "chris@example.com", "password": "hunter2"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --- login ---

def test_login_success_returns_token_and_user(client):
    c, _ = client
    r = c.post("/auth/login", json={"email": "chris@example.com", "password": "hunter2"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "chris@example.com"
    assert body["user"]["name"] == "Chris"
    assert "password_hash" not in body["user"]


def test_login_is_case_insensitive_on_email(client):
    c, _ = client
    r = c.post("/auth/login", json={"email": "  CHRIS@Example.com ", "password": "hunter2"})
    assert r.status_code == 200


def test_login_wrong_password_401(client):
    c, _ = client
    r = c.post("/auth/login", json={"email": "chris@example.com", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    c, _ = client
    r = c.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever"})
    assert r.status_code == 401


def test_login_user_without_password_hash_401(client):
    c, _ = client
    r = c.post("/auth/login", json={"email": "np@example.com", "password": "anything"})
    assert r.status_code == 401


# --- /auth/me + protected routers ---

def test_me_with_valid_token(client):
    c, _ = client
    token = _token(client)
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "chris@example.com"


def test_me_without_token_401(client):
    c, _ = client
    assert c.get("/auth/me").status_code == 401


def test_protected_route_requires_token(client):
    c, _ = client
    # /gamification is gated; no token → 401.
    assert c.get("/gamification?owner_id=1").status_code == 401


def test_protected_route_with_token_succeeds(client):
    c, _ = client
    token = _token(client)
    r = c.get("/gamification?owner_id=1", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_garbage_token_401(client):
    c, _ = client
    r = c.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_health_is_public(client):
    c, _ = client
    assert c.get("/health").status_code == 200


# --- service-level unit tests ---

def test_password_hash_roundtrip():
    h = auth_service.hash_password("correct horse")
    assert auth_service.verify_password("correct horse", h) is True
    assert auth_service.verify_password("wrong", h) is False


def test_verify_password_handles_missing_and_malformed():
    assert auth_service.verify_password("x", None) is False
    assert auth_service.verify_password("x", "not-a-bcrypt-hash") is False


def test_password_over_72_bytes_rejected():
    with pytest.raises(ValueError):
        auth_service.hash_password("a" * 73)


def test_jwt_roundtrip():
    token = auth_service.create_access_token(42)
    assert auth_service.decode_access_token(token) == 42


def test_decode_rejects_tampered_token():
    token = auth_service.create_access_token(42)
    with pytest.raises(jwt.PyJWTError):
        auth_service.decode_access_token(token + "x")


def test_auth_not_configured_when_secret_blank(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "auth_secret", "")
    with pytest.raises(auth_service.AuthNotConfigured):
        auth_service.create_access_token(1)
