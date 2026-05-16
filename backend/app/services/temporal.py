"""Temporal correction factor (Section 4, step 3 of the spec).

Chronic under-estimators get realistic blocks automatically: multiply every
LLM `est_minutes` by `mean(actual / estimated)` from this owner's prior
execution_log rows. Clamp to [0.5, 3.0] so a few outliers can't blow up
future estimates. Fall back to 1.0 (identity) until we have enough samples.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExecutionLog

MIN_SAMPLES = 3
CLAMP_LOW = 0.5
CLAMP_HIGH = 3.0


def correction_factor(session: Session, user_id: int) -> float:
    rows = session.execute(
        select(ExecutionLog.estimated_minutes, ExecutionLog.actual_minutes).where(
            ExecutionLog.user_id == user_id
        )
    ).all()
    ratios = [actual / est for est, actual in rows if est and est > 0]
    if len(ratios) < MIN_SAMPLES:
        return 1.0
    return max(CLAMP_LOW, min(CLAMP_HIGH, sum(ratios) / len(ratios)))


def apply_correction(est_minutes: int, factor: float) -> int:
    """Apply factor and snap to at least 5 minutes (the schema's lower bound)."""
    return max(5, round(est_minutes * factor))
