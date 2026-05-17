"""Test fixtures — an in-memory SQLite session with the schema applied."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401 — register models on Base.metadata

# Never let the background APScheduler fire during tests — would race with the
# in-test session and cause flaky failures.
settings.enable_scheduler_loop = False


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
