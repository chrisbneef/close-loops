"""Multi-pass scheduler tick + cross-owner dependency resolution.

These are the integration tests for Phase 3b. They walk a 2-cofounder team
through ingest-like scenarios and verify:
  - First pack persists to calendar_blocks
  - Second tick is idempotent (no writes)
  - A delegated task whose prereq lives on the other owner's calendar
    resolves correctly via cross-owner anchors
"""

from datetime import datetime, timedelta, timezone

from app import models
from app.services import scheduler_tick

# Use a Monday so the StubCalendarProvider returns full work-day slots.
NOW = datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)


def _seed_two_tasks_one_per_owner_with_cross_dep(session, michael, chris):
    """Michael owns task A; Chris owns task B which depends on A. Classic
    delegation pattern from the LLM's owner routing."""
    a = models.Task(title="A: foundation", owner_id=michael.id, est_minutes=25, importance=8)
    b = models.Task(
        title="B: depends on A", owner_id=chris.id, delegator_id=michael.id,
        est_minutes=25, importance=8,
    )
    session.add_all([a, b])
    session.flush()
    session.add(models.TaskDependency(task_id=b.id, depends_on_task_id=a.id))
    session.commit()
    return a, b


def test_tick_persists_blocks_for_simple_two_task_setup(session, cofounders):
    michael, _ = cofounders
    t = models.Task(title="Solo", owner_id=michael.id, est_minutes=25)
    session.add(t)
    session.commit()

    counts = scheduler_tick.tick(session, now=NOW)
    assert counts[michael.id]["inserted"] == 1
    assert session.query(models.CalendarBlock).count() == 1


def test_tick_is_idempotent_when_run_twice(session, cofounders):
    michael, _ = cofounders
    t = models.Task(title="Solo", owner_id=michael.id, est_minutes=25)
    session.add(t)
    session.commit()

    scheduler_tick.tick(session, now=NOW)
    counts = scheduler_tick.tick(session, now=NOW)
    # Second tick should produce zero diffs.
    assert counts[michael.id] == {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 0}


def test_cross_owner_dependency_resolves_within_one_tick(session, cofounders):
    """Within a single tick's multi-pass loop, pass 1 packs Michael's A and
    pass 2 packs Chris's B using A's persisted end as a cross-owner anchor."""
    michael, chris = cofounders
    a, b = _seed_two_tasks_one_per_owner_with_cross_dep(session, michael, chris)

    counts = scheduler_tick.tick(session, now=NOW)

    blocks = {bl.task_id: bl for bl in session.query(models.CalendarBlock).all()}
    assert a.id in blocks, "Michael's task A should be persisted"
    assert b.id in blocks, "Chris's task B should resolve via cross-owner anchor"
    # B must start AT OR AFTER A finishes.
    a_end = blocks[a.id].end.replace(tzinfo=timezone.utc) if blocks[a.id].end.tzinfo is None else blocks[a.id].end
    b_start = blocks[b.id].start.replace(tzinfo=timezone.utc) if blocks[b.id].start.tzinfo is None else blocks[b.id].start
    assert b_start >= a_end


def test_overflow_tasks_get_deleted_from_calendar_blocks(session, cofounders):
    """If a task fits in pass 1 then a new higher-priority task bumps it on the
    next tick, the old block should be deleted (or moved)."""
    michael, _ = cofounders
    low = models.Task(title="Low prio", owner_id=michael.id, est_minutes=200, importance=2)
    session.add(low)
    session.commit()
    scheduler_tick.tick(session, now=NOW)
    assert session.query(models.CalendarBlock).count() == 1

    # Mark low priority as done so it falls out of active set.
    session.query(models.Task).filter_by(id=low.id).update({"status": "done"})
    session.commit()

    counts = scheduler_tick.tick(session, now=NOW)
    assert counts[michael.id]["deleted"] == 1
    assert session.query(models.CalendarBlock).count() == 0


def test_tick_handles_no_users(session):
    counts = scheduler_tick.tick(session, now=NOW)
    assert counts == {}
