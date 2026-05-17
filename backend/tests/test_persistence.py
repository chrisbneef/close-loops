"""Diff-and-apply logic for calendar_blocks."""

from datetime import datetime, timedelta, timezone

from app import models
from app.services.packer import ScheduledBlock
from app.services.persistence import apply_diff_for_owner, changed

NOW = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)


def _seed_tasks(session, owner, n: int) -> list[models.Task]:
    tasks = [models.Task(title=f"T{i}", owner_id=owner.id, est_minutes=25) for i in range(n)]
    session.add_all(tasks)
    session.commit()
    return tasks


def _block(task_id: int, offset_min: int, dur: int = 25) -> ScheduledBlock:
    start = NOW + timedelta(minutes=offset_min)
    return ScheduledBlock(task_id=task_id, title=f"T{task_id}", start=start, end=start + timedelta(minutes=dur), priority=1.0)


def test_inserts_when_no_existing_blocks(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 2)
    counts = apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0), _block(tasks[1].id, 30)])
    session.commit()
    assert counts == {"inserted": 2, "updated": 0, "deleted": 0, "skipped_locked": 0}
    assert session.query(models.CalendarBlock).count() == 2


def test_second_call_is_idempotent(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 2)
    proposal = [_block(tasks[0].id, 0), _block(tasks[1].id, 30)]
    apply_diff_for_owner(session, michael.id, proposal)
    session.commit()
    counts = apply_diff_for_owner(session, michael.id, proposal)
    session.commit()
    assert counts == {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 0}
    assert not changed(counts)


def test_updates_when_time_differs(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)
    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)])
    session.commit()
    counts = apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 60)])
    session.commit()
    assert counts["updated"] == 1
    block = session.query(models.CalendarBlock).one()
    assert block.start.replace(tzinfo=timezone.utc) == NOW + timedelta(minutes=60)


def test_deletes_when_task_falls_out_of_proposal(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 2)
    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0), _block(tasks[1].id, 30)])
    session.commit()
    counts = apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)])  # task[1] dropped
    session.commit()
    assert counts["deleted"] == 1
    assert session.query(models.CalendarBlock).count() == 1


def test_preserves_locked_blocks(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)
    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)])
    session.commit()
    # User locks the block manually.
    block = session.query(models.CalendarBlock).one()
    block.locked = True
    session.commit()
    # New proposal would move it.
    counts = apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 120)])
    session.commit()
    assert counts == {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 1}
    persisted = session.query(models.CalendarBlock).one()
    assert persisted.start.replace(tzinfo=timezone.utc) == NOW  # unchanged


def test_only_touches_blocks_for_this_owner(session, cofounders):
    michael, chris = cofounders
    m_task = models.Task(title="m", owner_id=michael.id, est_minutes=25)
    c_task = models.Task(title="c", owner_id=chris.id, est_minutes=25)
    session.add_all([m_task, c_task])
    session.commit()
    # Seed Chris's block.
    session.add(models.CalendarBlock(task_id=c_task.id, start=NOW, end=NOW + timedelta(minutes=25)))
    session.commit()
    # Apply diff for Michael with an empty proposal — Chris's block must be untouched.
    counts = apply_diff_for_owner(session, michael.id, [])
    session.commit()
    assert counts == {"inserted": 0, "updated": 0, "deleted": 0, "skipped_locked": 0}
    assert session.query(models.CalendarBlock).filter_by(task_id=c_task.id).count() == 1
