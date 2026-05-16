from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.services.temporal import CLAMP_HIGH, CLAMP_LOW, apply_correction, correction_factor


def _log(user_id: int, est: int, actual: int) -> models.ExecutionLog:
    now = datetime.now(timezone.utc)
    return models.ExecutionLog(
        task_id=1,
        user_id=user_id,
        estimated_minutes=est,
        actual_minutes=actual,
        started_at=now - timedelta(minutes=actual),
        finished_at=now,
    )


def test_no_history_returns_identity(session, cofounders):
    michael, _ = cofounders
    assert correction_factor(session, michael.id) == 1.0


def test_below_threshold_returns_identity(session, cofounders):
    michael, _ = cofounders
    # Only 2 samples — below MIN_SAMPLES=3, so we don't yet trust the ratio.
    # ExecutionLog requires a valid task_id (FK), so create a placeholder Task.
    placeholder = models.Task(title="placeholder", owner_id=michael.id, est_minutes=10)
    session.add(placeholder)
    session.flush()
    session.add_all([
        models.ExecutionLog(
            task_id=placeholder.id, user_id=michael.id,
            estimated_minutes=10, actual_minutes=30,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        ),
        models.ExecutionLog(
            task_id=placeholder.id, user_id=michael.id,
            estimated_minutes=20, actual_minutes=60,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        ),
    ])
    session.commit()
    assert correction_factor(session, michael.id) == 1.0


def test_consistent_2x_underestimator(session, cofounders):
    michael, _ = cofounders
    placeholder = models.Task(title="placeholder", owner_id=michael.id, est_minutes=10)
    session.add(placeholder)
    session.flush()
    for est, actual in [(10, 20), (15, 30), (20, 40), (5, 10)]:
        session.add(models.ExecutionLog(
            task_id=placeholder.id, user_id=michael.id,
            estimated_minutes=est, actual_minutes=actual,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        ))
    session.commit()
    assert correction_factor(session, michael.id) == pytest.approx(2.0)


def test_clamps_high(session, cofounders):
    michael, _ = cofounders
    placeholder = models.Task(title="placeholder", owner_id=michael.id, est_minutes=10)
    session.add(placeholder)
    session.flush()
    for est, actual in [(5, 100), (5, 100), (5, 100)]:
        session.add(models.ExecutionLog(
            task_id=placeholder.id, user_id=michael.id,
            estimated_minutes=est, actual_minutes=actual,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        ))
    session.commit()
    assert correction_factor(session, michael.id) == CLAMP_HIGH


def test_clamps_low(session, cofounders):
    michael, _ = cofounders
    placeholder = models.Task(title="placeholder", owner_id=michael.id, est_minutes=10)
    session.add(placeholder)
    session.flush()
    for est, actual in [(60, 5), (60, 5), (60, 5)]:
        session.add(models.ExecutionLog(
            task_id=placeholder.id, user_id=michael.id,
            estimated_minutes=est, actual_minutes=actual,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        ))
    session.commit()
    assert correction_factor(session, michael.id) == CLAMP_LOW


def test_apply_correction_floors_at_5():
    assert apply_correction(10, 0.1) == 5  # 1 → floored to 5
    assert apply_correction(20, 2.0) == 40
    assert apply_correction(15, 1.5) == 22  # round half-to-even = 22
