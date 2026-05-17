"""Multi-pass scheduler tick.

One tick:
  1. Iterate users in id order.
  2. For each, pack + apply diff to calendar_blocks.
  3. If any user's diff made changes, run another pass — cross-owner anchors
     freshly persisted in pass N may unblock dependents in pass N+1.
  4. Cap at MAX_PASSES so a pathological cycle can't spin forever.

Tick is idempotent: calling it twice in a row with no upstream changes
produces zero writes on the second call (diff sees identical state).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.services import persistence, scheduler

logger = logging.getLogger(__name__)

MAX_PASSES = 3  # 2 is the typical fixed point; 3 catches edge cases.


def tick(session: Session, *, now: Optional[datetime] = None) -> dict[int, dict[str, int]]:
    """Run packing + persistence for every active user. Returns
    {user_id: aggregate_diff_counts} summed across all passes — so a real insert
    in pass 1 isn't masked by a no-op in pass 2."""
    now = now or datetime.now(timezone.utc)
    user_ids = [
        row[0]
        for row in session.execute(select(User.id).order_by(User.id)).all()
    ]
    keys = ("inserted", "updated", "deleted", "skipped_locked")
    final_counts: dict[int, dict[str, int]] = {
        user_id: {k: 0 for k in keys} for user_id in user_ids
    }

    for pass_n in range(1, MAX_PASSES + 1):
        any_change = False
        for user_id in user_ids:
            _, _, counts = scheduler.apply_schedule_for_owner(session, user_id, now=now)
            for k in keys:
                final_counts[user_id][k] += counts.get(k, 0)
            if persistence.changed(counts):
                any_change = True
        session.commit()
        logger.info("scheduler tick pass=%s any_change=%s", pass_n, any_change)
        if not any_change:
            break
    return final_counts
