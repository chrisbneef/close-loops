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


# --- provider mirror tests (Phase 4) ---

class _FakeProvider:
    """Records every call so tests can assert the mirror happened correctly."""

    def __init__(self):
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[str] = []
        self._next_id = 0

    def free_slots(self, *_args, **_kwargs):
        return []

    def create_event(self, *, start, end, title, task_id) -> str:
        self._next_id += 1
        event_id = f"gcal-{self._next_id}"
        self.created.append({"event_id": event_id, "task_id": task_id, "title": title, "start": start, "end": end})
        return event_id

    def update_event(self, *, event_id, start, end, title) -> None:
        self.updated.append({"event_id": event_id, "title": title, "start": start, "end": end})

    def delete_event(self, *, event_id) -> None:
        self.deleted.append(event_id)


def test_insert_mirrors_to_provider_and_stores_event_id(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 2)
    provider = _FakeProvider()

    apply_diff_for_owner(
        session, michael.id,
        [_block(tasks[0].id, 0), _block(tasks[1].id, 30)],
        provider=provider,
    )
    session.commit()

    assert len(provider.created) == 2
    rows = session.query(models.CalendarBlock).all()
    for row in rows:
        assert row.gcal_event_id is not None
        assert row.gcal_event_id.startswith("gcal-")


def test_update_mirrors_to_provider_with_existing_event_id(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)
    provider = _FakeProvider()

    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)], provider=provider)
    session.commit()

    # Move the block — should mirror as update_event, not create_event.
    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 60)], provider=provider)
    session.commit()

    assert len(provider.created) == 1  # the original
    assert len(provider.updated) == 1
    assert provider.updated[0]["event_id"] == provider.created[0]["event_id"]


def test_delete_mirrors_to_provider(session, cofounders):
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)
    provider = _FakeProvider()

    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)], provider=provider)
    session.commit()
    event_id = provider.created[0]["event_id"]

    # Empty proposal → DB delete + mirror delete.
    apply_diff_for_owner(session, michael.id, [], provider=provider)
    session.commit()

    assert provider.deleted == [event_id]
    assert session.query(models.CalendarBlock).count() == 0


def test_update_skips_mirror_when_no_event_id_stored(session, cofounders):
    """Earlier create_event failed → row has no gcal_event_id. Subsequent
    update shouldn't try to update_event with a missing id."""
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)
    # Persist the row directly with no gcal_event_id (simulates create_event failure).
    session.add(models.CalendarBlock(
        task_id=tasks[0].id, start=NOW, end=NOW + timedelta(minutes=25), gcal_event_id=None
    ))
    session.commit()

    provider = _FakeProvider()
    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 60)], provider=provider)
    session.commit()
    assert provider.updated == []  # no upstream update attempted


def test_provider_error_does_not_block_db_insert(session, cofounders):
    """Network blip during create_event shouldn't fail the whole tick."""
    michael, _ = cofounders
    tasks = _seed_tasks(session, michael, 1)

    class FlakyProvider(_FakeProvider):
        def create_event(self, **kwargs):
            raise RuntimeError("transient google failure")

    apply_diff_for_owner(session, michael.id, [_block(tasks[0].id, 0)], provider=FlakyProvider())
    session.commit()

    row = session.query(models.CalendarBlock).one()
    assert row.gcal_event_id is None  # we tried, it failed, row exists without an upstream id
