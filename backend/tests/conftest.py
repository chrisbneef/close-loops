"""Test fixtures — an in-memory SQLite session with the schema applied."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app.main import app
from app.security import get_current_user
from app import models  # noqa: F401 — register models on Base.metadata

# Never let the background APScheduler fire during tests — would race with the
# in-test session and cause flaky failures.
settings.enable_scheduler_loop = False
# Deterministic signing key so auth tokens encode/decode in tests.
settings.auth_secret = "test-secret-not-for-production"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_auth: exercise the real get_current_user dependency (no bypass)",
    )


@pytest.fixture(autouse=True)
def _bypass_auth(request):
    """Most router tests predate auth and call protected endpoints without a
    token. Override the auth dependency to a no-op identity so they keep
    testing business logic. Tests marked @pytest.mark.real_auth opt out and
    hit the genuine 401/JWT path."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[get_current_user] = lambda: models.User(
        id=0, name="test", role="cofounder", timezone="UTC"
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def session() -> Session:
    # StaticPool is required for sqlite:///:memory: — each new connection otherwise
    # gets a fresh empty database, so seeded data vanishes between operations.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def cofounders(session):
    michael = models.User(name="Michael", role="cofounder", capacity_score=75.0, timezone="UTC")
    chris = models.User(name="Chris", role="cofounder", capacity_score=80.0, timezone="UTC")
    session.add_all([michael, chris])
    session.commit()
    return michael, chris
