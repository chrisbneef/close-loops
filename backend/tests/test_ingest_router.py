"""HTTP-level test of POST /ingest with the LLM mocked at the service boundary."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_session
from app.main import app
from app.schemas import LLMDecomposition, LLMTask
from app.services import llm


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override_session

    # Seed a cofounder so the default owner-resolution path works.
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder", capacity_score=75.0))
        s.commit()

    # Stub the network call.
    def _fake_decompose(raw_goal: str, **_kwargs):
        return LLMDecomposition(
            reasoning="stubbed for the router test",
            tasks=[
                LLMTask(title="One", est_minutes=20, importance=8),
                LLMTask(title="Two", est_minutes=15, importance=6, depends_on=["One"]),
            ],
        )

    monkeypatch.setattr(llm, "decompose", _fake_decompose)

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_post_ingest_returns_structured_response(client):
    r = client.post("/ingest", json={"raw_goal": "Get the Q3 webinar live"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reasoning"].startswith("stubbed")
    assert len(body["tasks"]) == 2
    assert len(body["dependency_edges"]) == 1
    assert body["temporal_correction_factor"] == 1.0


def test_post_ingest_rejects_unknown_owner(client):
    r = client.post("/ingest", json={"raw_goal": "valid length goal", "owner_id": 9999})
    assert r.status_code == 400
    assert "owner_id=9999" in r.json()["detail"]


def test_post_ingest_validates_short_goal(client):
    r = client.post("/ingest", json={"raw_goal": "no"})
    assert r.status_code == 422  # pydantic min_length


def test_post_ingest_503_when_api_key_missing(monkeypatch):
    """No LLM stub + empty key → clean 503, not a 500 leak."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.config import settings
    from app.services import llm as llm_module

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    # Don't stub decompose — let the real key check fire.

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as s:
        s.add(models.User(name="Michael", role="cofounder"))
        s.commit()

    def _override_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override_session
    try:
        c = TestClient(app)
        r = c.post("/ingest", json={"raw_goal": "valid length goal"})
        assert r.status_code == 503
        assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
