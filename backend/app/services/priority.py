"""Section 5.1 priority math: P(t) for every active task.

P(t) = α · urgency(D, C) + β · importance + γ · momentum − δ · load · (1 − circadian(C))

- urgency:   1 / hours_until_deadline. Guarded against div-by-zero and None.
- importance: LLM-set 1..10, normalized to 0..1.
- momentum:  per-task downstream-dependents count (computed by the momentum module).
- load:      (importance/10) * (est_minutes/60), so demanding + long tasks weigh more.
- circadian: looks up the requester's energy_curve at the current local hour
             (0..1 = energy available). The penalty kicks in when energy is LOW.
"""

from __future__ import annotations

import math
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models import Task

# When deadline is None we still want urgency to decay gracefully — use a far
# but finite horizon. Past deadlines clamp to a tiny epsilon so urgency goes
# very high without becoming inf.
DEFAULT_HORIZON_DAYS = 90
PAST_DEADLINE_EPSILON_HOURS = 0.01  # 36 seconds — a strong but finite urgency spike

# Flat curve when the user hasn't supplied a personal energy_curve.
DEFAULT_ENERGY = [0.5] * 24


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite drops tzinfo on DateTime(timezone=True) reads; Postgres preserves it.
    Normalize so the rest of the math doesn't have to think about it."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hours_until_deadline(deadline: Optional[datetime], now: datetime) -> float:
    """Returns hours until the deadline, with the spec's div-by-zero / null guards."""
    now = _as_utc(now)
    deadline = _as_utc(deadline)
    if deadline is None:
        return DEFAULT_HORIZON_DAYS * 24.0
    delta_hours = (deadline - now).total_seconds() / 3600.0
    return max(delta_hours, PAST_DEADLINE_EPSILON_HOURS)


def urgency(deadline: Optional[datetime], now: datetime) -> float:
    """1 / hours_until_deadline. Always finite, always positive."""
    return 1.0 / hours_until_deadline(deadline, now)


def circadian_energy(now: datetime, energy_curve: Optional[list], timezone_name: str) -> float:
    """Looks up the user's energy_curve at the current LOCAL hour. Returns 0..1.

    Falls back to a flat 0.5 if no curve is set."""
    curve = energy_curve or DEFAULT_ENERGY
    if len(curve) != 24:
        # Malformed curve — degrade gracefully, don't crash the scheduler.
        return 0.5
    try:
        tz = zoneinfo.ZoneInfo(timezone_name or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        tz = zoneinfo.ZoneInfo("UTC")
    local_hour = _as_utc(now).astimezone(tz).hour
    # Clamp the curve entry to [0, 1] in case it's noisy.
    return max(0.0, min(1.0, float(curve[local_hour])))


def load(task: Task) -> float:
    """Cognitive demand proxy: importance × duration, normalized so a 60-min
    importance-10 task has load == 1.0."""
    return (task.importance / 10.0) * (max(task.est_minutes, 1) / 60.0)


def compute_priority(
    task: Task,
    *,
    now: datetime,
    momentum_weight: float,
    owner_timezone: str,
    owner_energy_curve: Optional[list],
    alpha: float,
    beta: float,
    gamma: float,
    delta: float,
) -> float:
    """The full P(t) formula. Tunable via the SCHED_* env vars in app/config.py."""
    u = urgency(task.deadline, now)
    importance_norm = task.importance / 10.0
    energy = circadian_energy(now, owner_energy_curve, owner_timezone)
    load_penalty = load(task) * (1.0 - energy)
    score = (
        alpha * u
        + beta * importance_norm
        + gamma * momentum_weight
        - delta * load_penalty
    )
    # Guard against NaN propagation from malformed inputs.
    return score if math.isfinite(score) else 0.0
