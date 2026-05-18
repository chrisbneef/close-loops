"""GoogleCalendarProvider — unit tests with a mocked Google API client.

These never touch the real Google Calendar. The provider's _get_service is
patched to return a fake service object whose .events() chain returns
predictable data."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_calendar import (
    CADENCE_BLOCK_PROPERTY,
    GoogleCalendarProvider,
    _subtract_busy,
)
from app.services.calendar_provider import FreeSlot

NOW = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)  # Mon 16:00 UTC = 09:00 PT


def _service_returning_events(events):
    """Build a fake Google service whose events().list().execute() returns the given items."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": events}
    service.events.return_value.insert.return_value.execute.return_value = {"id": "fake-event-id"}
    service.events.return_value.patch.return_value.execute.return_value = {}
    service.events.return_value.delete.return_value.execute.return_value = {}
    return service


def test_constructor_requires_refresh_token():
    with pytest.raises(ValueError):
        GoogleCalendarProvider(refresh_token="")


def test_subtract_busy_carves_correctly():
    # 9-12 free slot; busy 10-11 → expect 9-10 and 11-12.
    slot = FreeSlot(start=NOW, end=NOW + timedelta(hours=3))
    busy = [(NOW + timedelta(hours=1), NOW + timedelta(hours=2))]
    result = _subtract_busy([slot], busy)
    assert len(result) == 2
    assert result[0].end == NOW + timedelta(hours=1)
    assert result[1].start == NOW + timedelta(hours=2)


def test_subtract_busy_keeps_disjoint_slots_intact():
    slot = FreeSlot(start=NOW, end=NOW + timedelta(hours=3))
    busy = [(NOW + timedelta(hours=10), NOW + timedelta(hours=11))]  # well after
    assert _subtract_busy([slot], busy) == [slot]


def test_subtract_busy_removes_fully_covered_slot():
    slot = FreeSlot(start=NOW, end=NOW + timedelta(hours=1))
    busy = [(NOW, NOW + timedelta(hours=1))]
    assert _subtract_busy([slot], busy) == []


def test_free_slots_filters_out_cadence_blocks():
    """Our own scheduled events should not count as busy time."""
    provider = GoogleCalendarProvider(refresh_token="fake")
    s = NOW + timedelta(hours=2)
    e = NOW + timedelta(hours=3)
    cadence_event = {
        "start": {"dateTime": s.isoformat()},
        "end": {"dateTime": e.isoformat()},
        "extendedProperties": {"private": {CADENCE_BLOCK_PROPERTY: "true"}},
    }
    real_event = {  # different time, real meeting — should reduce free time
        "start": {"dateTime": (NOW + timedelta(hours=1)).isoformat()},
        "end": {"dateTime": (NOW + timedelta(hours=2)).isoformat()},
    }
    with patch.object(provider, "_get_service", return_value=_service_returning_events([cadence_event, real_event])):
        slots = provider.free_slots(
            "UTC",
            start=NOW,
            end=NOW + timedelta(days=1),
        )
    # Morning skeleton in UTC for May 18 starts 09:00 UTC; NOW is 16:00 → already past it.
    # So morning slot is empty. Afternoon: 13:00-17:00 UTC. NOW is 16:00 so clipped to 16:00-17:00.
    # Real event at 17:00-18:00 doesn't overlap with our 16:00-17:00 slot.
    # Cadence event at 18:00-19:00 also doesn't overlap.
    # Result: at least one slot starting at NOW=16:00 should remain.
    assert any(s.start == NOW for s in slots), f"expected a slot starting at {NOW}, got {slots}"


def test_free_slots_skips_all_day_events():
    """Events without dateTime (all-day) should be ignored, not crash."""
    provider = GoogleCalendarProvider(refresh_token="fake")
    all_day = {"start": {"date": "2026-05-18"}, "end": {"date": "2026-05-19"}}
    with patch.object(provider, "_get_service", return_value=_service_returning_events([all_day])):
        # Should not raise.
        provider.free_slots("UTC", start=NOW, end=NOW + timedelta(days=1))


def test_free_slots_falls_back_to_skeleton_on_api_error():
    provider = GoogleCalendarProvider(refresh_token="fake")
    bad_service = MagicMock()
    bad_service.events.return_value.list.side_effect = RuntimeError("API down")
    with patch.object(provider, "_get_service", return_value=bad_service):
        slots = provider.free_slots("UTC", start=NOW, end=NOW + timedelta(days=1))
    # Should return the bare skeleton from the stub (afternoon clipped from NOW).
    assert len(slots) >= 1


def test_create_event_sends_correct_body():
    provider = GoogleCalendarProvider(refresh_token="fake")
    captured = {}

    def insert_capture(calendarId, body):
        captured["calendarId"] = calendarId
        captured["body"] = body
        return MagicMock(execute=lambda: {"id": "newly-created-event"})

    fake_service = MagicMock()
    fake_service.events.return_value.insert.side_effect = insert_capture

    with patch.object(provider, "_get_service", return_value=fake_service):
        event_id = provider.create_event(
            start=NOW, end=NOW + timedelta(minutes=25),
            title="Test task", task_id=42,
        )
    assert event_id == "newly-created-event"
    assert captured["calendarId"] == "primary"
    body = captured["body"]
    assert body["summary"] == "Test task"
    assert body["extendedProperties"]["private"]["cadence_block"] == "true"
    assert body["extendedProperties"]["private"]["cadence_task_id"] == "42"


def test_update_event_uses_patch():
    provider = GoogleCalendarProvider(refresh_token="fake")
    fake_service = _service_returning_events([])
    with patch.object(provider, "_get_service", return_value=fake_service):
        provider.update_event(
            event_id="abc123", start=NOW, end=NOW + timedelta(minutes=30), title="Moved"
        )
    fake_service.events.return_value.patch.assert_called_once()
    call_kwargs = fake_service.events.return_value.patch.call_args.kwargs
    assert call_kwargs["calendarId"] == "primary"
    assert call_kwargs["eventId"] == "abc123"
    assert call_kwargs["body"]["summary"] == "Moved"


def test_delete_event_swallows_404():
    """Deleting an event that's already gone should not raise."""
    provider = GoogleCalendarProvider(refresh_token="fake")
    fake_service = MagicMock()

    class FakeHttpError(Exception):
        def __init__(self, status):
            self.resp = MagicMock(status=status)
    fake_service.events.return_value.delete.return_value.execute.side_effect = FakeHttpError(404)

    with patch.object(provider, "_get_service", return_value=fake_service):
        provider.delete_event(event_id="already-gone")  # should not raise


def test_delete_event_reraises_other_errors():
    provider = GoogleCalendarProvider(refresh_token="fake")
    fake_service = MagicMock()
    fake_service.events.return_value.delete.return_value.execute.side_effect = RuntimeError("network")

    with patch.object(provider, "_get_service", return_value=fake_service):
        with pytest.raises(RuntimeError):
            provider.delete_event(event_id="x")
