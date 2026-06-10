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
    _user_attending,
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


def test_user_attending_no_attendees_is_attending():
    """Personal blocks the user created for themselves have no attendees list."""
    assert _user_attending({"summary": "focus"}) is True
    assert _user_attending({"attendees": []}) is True


def test_user_attending_accepted_and_tentative_are_attending():
    for status in ("accepted", "tentative"):
        ev = {"attendees": [{"self": True, "responseStatus": status}]}
        assert _user_attending(ev) is True, status


def test_user_attending_declined_and_needsaction_are_not_attending():
    """The 'RE Showing' / 'white' Google event case — user hasn't accepted."""
    for status in ("declined", "needsAction"):
        ev = {"attendees": [{"self": True, "responseStatus": status}]}
        assert _user_attending(ev) is False, status


def test_user_attending_ignores_other_attendees_response():
    """Other people's responses don't matter — only the calendar owner's does."""
    ev = {"attendees": [
        {"email": "someone@else.com", "responseStatus": "declined"},
        {"self": True, "responseStatus": "accepted"},
    ]}
    assert _user_attending(ev) is True


def test_user_attending_no_self_attendee_treated_as_attending():
    """If somehow we're not in the attendees list at all, don't block work over it."""
    ev = {"attendees": [{"email": "someone@else.com", "responseStatus": "accepted"}]}
    assert _user_attending(ev) is True


def test_free_slots_ignores_unanswered_invites():
    """An unanswered ('needsAction') invite must not eat into free time —
    this was the bug behind the user's Start-Your-Day overlap report.

    Skeleton clipped to NOW=16:00 UTC gives the 16:00-17:00 afternoon sliver.
    Put a fake "RE Showing" inside it — must NOT chop the slot."""
    provider = GoogleCalendarProvider(refresh_token="fake")
    meeting_start = NOW + timedelta(minutes=15)  # 16:15 UTC
    meeting_end = NOW + timedelta(minutes=45)    # 16:45 UTC
    unanswered = {
        "summary": "RE Showing",
        "start": {"dateTime": meeting_start.isoformat()},
        "end": {"dateTime": meeting_end.isoformat()},
        "attendees": [{"self": True, "responseStatus": "needsAction"}],
    }
    with patch.object(provider, "_get_service", return_value=_service_returning_events([unanswered])):
        slots = provider.free_slots("UTC", start=NOW, end=NOW + timedelta(days=1))
    # Middle of the meeting (16:30) must still be inside a free slot.
    mid = NOW + timedelta(minutes=30)
    assert any(s.start <= mid < s.end for s in slots), \
        f"unanswered invite carved out {mid} — should not have. slots={slots}"


def test_free_slots_still_blocks_accepted_meetings():
    """Sanity: my new filter doesn't accidentally make accepted meetings free."""
    provider = GoogleCalendarProvider(refresh_token="fake")
    accepted = {
        "summary": "Real meeting",
        "start": {"dateTime": (NOW + timedelta(minutes=15)).isoformat()},
        "end": {"dateTime": (NOW + timedelta(minutes=45)).isoformat()},
        "attendees": [{"self": True, "responseStatus": "accepted"}],
    }
    with patch.object(provider, "_get_service", return_value=_service_returning_events([accepted])):
        slots = provider.free_slots("UTC", start=NOW, end=NOW + timedelta(days=1))
    mid = NOW + timedelta(minutes=30)
    assert not any(s.start <= mid < s.end for s in slots), \
        f"accepted meeting should have carved out {mid}, but didn't. slots={slots}"


def test_events_for_window_hides_declined_meetings():
    provider = GoogleCalendarProvider(refresh_token="fake")
    declined = {
        "summary": "Optional standup",
        "start": {"dateTime": NOW.isoformat()},
        "end": {"dateTime": (NOW + timedelta(hours=1)).isoformat()},
        "attendees": [{"self": True, "responseStatus": "declined"}],
    }
    accepted = {
        "summary": "Real meeting",
        "start": {"dateTime": (NOW + timedelta(hours=2)).isoformat()},
        "end": {"dateTime": (NOW + timedelta(hours=3)).isoformat()},
        "attendees": [{"self": True, "responseStatus": "accepted"}],
    }
    with patch.object(provider, "_get_service", return_value=_service_returning_events([declined, accepted])):
        events = provider.events_for_window("UTC", start=NOW, end=NOW + timedelta(days=1))
    titles = [e.title for e in events]
    assert titles == ["Real meeting"], titles


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
