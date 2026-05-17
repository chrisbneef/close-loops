"""APScheduler loop: ticks every ~60 seconds.

Started by main.py's FastAPI lifespan; stopped on shutdown. Each tick runs on
a fresh SQLAlchemy session — never reuses request sessions.

Gated behind `settings.enable_scheduler_loop` so tests don't start a background
job by accident (the test conftest sets this to False).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.services import scheduler_tick

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _tick_job() -> None:
    session = SessionLocal()
    try:
        scheduler_tick.tick(session)
    except Exception:
        logger.exception("scheduler_loop tick failed")
        session.rollback()
    finally:
        session.close()


def start() -> None:
    global _scheduler
    if not settings.enable_scheduler_loop:
        logger.info("scheduler_loop disabled (settings.enable_scheduler_loop=False)")
        return
    if _scheduler is not None:
        logger.warning("scheduler_loop already started")
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_tick_job, "interval", seconds=settings.scheduler_tick_seconds, id="cadence_tick")
    _scheduler.start()
    logger.info("scheduler_loop started: tick every %ss", settings.scheduler_tick_seconds)


def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("scheduler_loop stopped")
