from datetime import datetime, timedelta, timezone

from app.services.calendar_provider import FreeSlot
from app.services.packer import ScheduledBlock, TaskCandidate, pack

NOW = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)  # Mon 9am UTC

# A single 3-hour morning slot, useful for many tests.
ONE_MORNING = [FreeSlot(start=NOW, end=NOW + timedelta(hours=3))]


def _t(task_id, *, est=25, prio=1.0, deps=None, immutable=False, locked_start=None) -> TaskCandidate:
    return TaskCandidate(
        task_id=task_id,
        title=f"T{task_id}",
        est_minutes=est,
        priority=prio,
        depends_on=deps or [],
        is_immutable=immutable,
        locked_start=locked_start,
    )


def test_higher_priority_packs_first():
    tasks = [_t(1, prio=1.0), _t(2, prio=10.0), _t(3, prio=5.0)]
    blocks, unscheduled = pack(tasks, ONE_MORNING)
    # All three fit (25*3 = 75 min in 180 min slot).
    by_start = sorted(blocks, key=lambda b: b.start)
    assert [b.task_id for b in by_start] == [2, 3, 1]  # priority desc
    assert unscheduled == []


def test_respects_dependency_ordering():
    # T1 depends on T2; T2 has lower priority. T2 must still come first.
    tasks = [_t(1, prio=10.0, deps=[2]), _t(2, prio=1.0)]
    blocks, unscheduled = pack(tasks, ONE_MORNING)
    starts = {b.task_id: b.start for b in blocks}
    assert starts[2] < starts[1]
    assert unscheduled == []


def test_drops_task_with_unscheduled_dependency():
    # T1 depends on T99 which doesn't exist in the candidate list.
    tasks = [_t(1, prio=10.0, deps=[99])]
    blocks, unscheduled = pack(tasks, ONE_MORNING)
    assert blocks == []
    assert unscheduled == [1]


def test_immutable_anchor_is_placed_first_and_not_moved():
    locked = NOW + timedelta(hours=1)  # 10am
    tasks = [
        _t(1, est=60, prio=100.0),  # would normally win
        _t(2, est=30, prio=1.0, immutable=True, locked_start=locked),
    ]
    blocks, unscheduled = pack(tasks, ONE_MORNING)
    by_id = {b.task_id: b for b in blocks}
    assert by_id[2].start == locked
    assert by_id[2].end == locked + timedelta(minutes=30)
    # T1 has to go around the anchor.
    assert by_id[1].end <= by_id[2].start or by_id[1].start >= by_id[2].end
    assert unscheduled == []


def test_immutable_anchor_carves_slot_correctly():
    """Anchor in the middle of the only slot should fragment it into [before, after]."""
    locked = NOW + timedelta(hours=1)
    anchor = _t(1, est=30, prio=1.0, immutable=True, locked_start=locked)
    # A 45-minute task should fit in the [9-10] fragment.
    fits_before = _t(2, est=45, prio=10.0)
    # A 2-hour task wouldn't fit in either fragment.
    too_big = _t(3, est=120, prio=5.0)
    blocks, unscheduled = pack([anchor, fits_before, too_big], ONE_MORNING)
    by_id = {b.task_id: b for b in blocks}
    assert by_id[2].start == NOW
    assert by_id[2].end == NOW + timedelta(minutes=45)
    assert 3 in unscheduled


def test_capacity_cap_rolls_overflow_into_unscheduled():
    # 3 hours of slot, but cap at 50 min/day. Only 2 x 25min tasks fit.
    tasks = [_t(i, prio=10 - i) for i in range(1, 5)]  # 4 candidates, priorities 9..6
    blocks, unscheduled = pack(tasks, ONE_MORNING, daily_capacity_minutes=50)
    assert len(blocks) == 2
    assert len(unscheduled) == 2
    # The two highest-priority should have been scheduled.
    scheduled_ids = {b.task_id for b in blocks}
    assert scheduled_ids == {1, 2}


def test_task_too_long_for_any_slot_goes_unscheduled():
    tasks = [_t(1, est=240, prio=10.0)]  # 4 hours, slot is 3
    blocks, unscheduled = pack(tasks, ONE_MORNING)
    assert blocks == []
    assert unscheduled == [1]


def test_empty_inputs_returns_empty_outputs():
    assert pack([], []) == ([], [])
    assert pack([_t(1)], []) == ([], [1])
    assert pack([], ONE_MORNING) == ([], [])
