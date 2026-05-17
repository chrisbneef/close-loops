"""Priority math — Section 5.1.

Critical guards covered:
- deadline=None → uses 90-day horizon, never divides by zero
- past deadline → clamps to a tiny epsilon (extreme urgency, still finite)
- malformed energy_curve → graceful fallback
- unknown timezone → falls back to UTC
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Task
from app.services import priority


def _task(**kw) -> Task:
    """Build an unsaved Task — we only need attribute access for priority math."""
    defaults = dict(
        id=1, title="T", owner_id=1, est_minutes=25, importance=5,
        priority_score=0.0, momentum_weight=0.0, status="pending",
        is_immutable=False,
    )
    defaults.update(kw)
    return Task(**defaults)


NOW = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


# ---------- hours_until_deadline + urgency guards ----------

def test_none_deadline_uses_horizon():
    h = priority.hours_until_deadline(None, NOW)
    assert h == priority.DEFAULT_HORIZON_DAYS * 24


def test_past_deadline_clamps_to_epsilon():
    past = NOW - timedelta(hours=5)
    h = priority.hours_until_deadline(past, NOW)
    assert h == priority.PAST_DEADLINE_EPSILON_HOURS


def test_urgency_finite_for_past_deadline():
    past = NOW - timedelta(days=10)
    u = priority.urgency(past, NOW)
    assert u == 1.0 / priority.PAST_DEADLINE_EPSILON_HOURS  # big but finite
    assert u < float("inf")


def test_urgency_for_future_deadline():
    future = NOW + timedelta(hours=10)
    assert priority.urgency(future, NOW) == pytest.approx(1 / 10.0)


def test_naive_deadline_treated_as_utc():
    # SQLite returns naive datetimes on reads from DateTime(timezone=True).
    naive_future = (NOW + timedelta(hours=2)).replace(tzinfo=None)
    h = priority.hours_until_deadline(naive_future, NOW)
    assert h == pytest.approx(2.0)


# ---------- circadian energy lookup ----------

def test_circadian_falls_back_to_flat_when_curve_missing():
    e = priority.circadian_energy(NOW, None, "UTC")
    assert e == 0.5


def test_circadian_reads_local_hour():
    curve = [0.0] * 24
    curve[20] = 1.0  # 8pm energy spike
    # NOW = 2026-05-17 12:00 UTC → 05:00 in America/Los_Angeles (PDT = UTC-7). energy[5] == 0.
    e_la = priority.circadian_energy(NOW, curve, "America/Los_Angeles")
    assert e_la == 0.0
    # NOW + 15h = 2026-05-18 03:00 UTC → 20:00 prev day in LA. energy[20] == 1.
    later = NOW + timedelta(hours=15)
    e_la_later = priority.circadian_energy(later, curve, "America/Los_Angeles")
    assert e_la_later == 1.0


def test_circadian_handles_malformed_curve():
    e = priority.circadian_energy(NOW, [0.5, 0.5], "UTC")  # only 2 elements
    assert e == 0.5  # falls back to flat default


def test_circadian_handles_unknown_timezone():
    e = priority.circadian_energy(NOW, None, "Mars/Olympus")
    assert e == 0.5  # falls back to flat default in UTC


# ---------- load proxy ----------

def test_load_scales_with_importance_and_duration():
    t = _task(importance=10, est_minutes=60)
    assert priority.load(t) == pytest.approx(1.0)
    t = _task(importance=5, est_minutes=30)
    assert priority.load(t) == pytest.approx(0.25)


# ---------- full P(t) ----------

def test_priority_high_importance_short_deadline_scores_highest():
    urgent_critical = _task(
        importance=10, est_minutes=25, deadline=NOW + timedelta(hours=2)
    )
    chill_low = _task(importance=2, est_minutes=25, deadline=NOW + timedelta(days=30))
    s_urgent = priority.compute_priority(
        urgent_critical, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=None, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    s_chill = priority.compute_priority(
        chill_low, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=None, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    assert s_urgent > s_chill


def test_priority_uses_momentum():
    base = _task(importance=5, est_minutes=25, deadline=NOW + timedelta(days=5))
    s0 = priority.compute_priority(
        base, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=None, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    s5 = priority.compute_priority(
        base, now=NOW, momentum_weight=5, owner_timezone="UTC",
        owner_energy_curve=None, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    assert s5 - s0 == pytest.approx(0.5 * 5)


def test_priority_low_energy_hour_penalizes_demanding_task():
    """A demanding task scored at a 0-energy hour vs full-energy hour: the
    0-energy hour gets a load penalty subtracted; full-energy doesn't."""
    t = _task(importance=10, est_minutes=60, deadline=NOW + timedelta(days=30))
    high_curve = [1.0] * 24
    low_curve = [0.0] * 24
    s_high = priority.compute_priority(
        t, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=high_curve, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    s_low = priority.compute_priority(
        t, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=low_curve, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    # load(t) = 1.0, delta=0.7, energy diff = 1.0 → s_high - s_low = 0.7
    assert s_high - s_low == pytest.approx(0.7)


def test_priority_never_returns_nan_or_inf():
    t = _task(deadline=NOW - timedelta(days=10))  # very past
    s = priority.compute_priority(
        t, now=NOW, momentum_weight=0, owner_timezone="UTC",
        owner_energy_curve=None, alpha=1.0, beta=1.0, gamma=0.5, delta=0.7,
    )
    import math
    assert math.isfinite(s)
