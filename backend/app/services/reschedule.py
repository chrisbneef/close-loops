"""Reschedule trigger.

Called from `/ingest` (and anywhere else state changes meaningfully) to force
an immediate scheduler pass. The APScheduler loop also runs ticks periodically,
but a fresh ingest shouldn't have to wait up to 60s for the next tick.

The tick runs on a fresh session so it doesn't share state with the caller's
in-flight transaction. The caller should have already committed their writes
before calling this — otherwise the tick won't see the new tasks.
"""

from __future__ import annotations

import logging

from app.db import SessionLocal
from app.services import scheduler_tick

logger = logging.getLogger(__name__)


def request_reschedule_for_owner(owner_id: int, reason: str = "") -> None:
    """Run a synchronous scheduler tick on a fresh session. The owner_id is
    currently used only for logging — the tick repacks every user because
    cross-owner dependencies mean an upstream owner's change can ripple."""
    logger.info("reschedule triggered owner_id=%s reason=%s", owner_id, reason)
    session = SessionLocal()
    try:
        counts = scheduler_tick.tick(session)
        logger.info("reschedule tick finished counts=%s", counts)
    except Exception:
        logger.exception("reschedule tick failed")
        session.rollback()
    finally:
        session.close()
