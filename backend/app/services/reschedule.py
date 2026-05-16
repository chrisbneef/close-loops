"""Reschedule trigger — stub for Phase 3.

The real implementation will live in app/services/scheduler.py and be driven by
APScheduler. For now this is a no-op the ingest pipeline can call without
caring whether the optimizer is wired up yet.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def request_reschedule_for_owner(owner_id: int, reason: str = "") -> None:
    logger.info("reschedule requested owner_id=%s reason=%s (Phase 3 stub)", owner_id, reason)
