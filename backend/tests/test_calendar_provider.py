from datetime import datetime, timezone

from app.services.calendar_provider import StubCalendarProvider


def _provider_at(fake_now_utc: datetime) -> StubCalendarProvider:
    return StubCalendarProvider(clock=lambda: fake_now_utc)


def test_returns_morning_and_afternoon_blocks_on_a_weekday():
    # Monday 2026-05-18, 06:00 UTC (before working hours in UTC).
    now = datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc)
    provider = _provider_at(now)
    slots = provider.free_slots("UTC", start=now, end=datetime(2026, 5, 18, 23, 0, tzinfo=timezone.utc))
    assert len(slots) == 2
    assert slots[0].start.hour == 9
    assert slots[0].end.hour == 12
    assert slots[1].start.hour == 13
    assert slots[1].end.hour == 17


def test_skips_weekend_days():
    # Sat 2026-05-23 → Sun 2026-05-24.
    start = datetime(2026, 5, 23, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
    provider = _provider_at(start)
    slots = provider.free_slots("UTC", start=start, end=end)
    assert slots == []  # both weekend days


def test_clips_slot_when_now_is_mid_morning():
    # Mon 2026-05-18, 10:30 UTC — we're in the morning slot.
    now = datetime(2026, 5, 18, 10, 30, tzinfo=timezone.utc)
    provider = _provider_at(now)
    slots = provider.free_slots("UTC", start=now, end=datetime(2026, 5, 18, 23, 0, tzinfo=timezone.utc))
    # Morning slot should now start at 10:30 instead of 09:00.
    assert slots[0].start == now
    assert slots[0].end.hour == 12
    assert slots[1].start.hour == 13


def test_user_timezone_shifts_slots():
    # Mon 2026-05-18 anywhere global.
    now = datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc)
    provider = _provider_at(now)
    slots = provider.free_slots(
        "America/Los_Angeles",
        start=now,
        end=datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
    )
    # 9:00 PT = 16:00 UTC during PDT (DST in effect in May).
    assert slots[0].start.hour == 16
    assert slots[0].end.hour == 19
    assert slots[1].start.hour == 20
    assert slots[1].end.hour == 24 % 24 or slots[1].end.hour == 0  # midnight UTC


def test_returns_empty_when_start_after_end():
    now = datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc)
    provider = _provider_at(now)
    assert provider.free_slots("UTC", start=now, end=now) == []


def test_unknown_timezone_falls_back_to_utc():
    now = datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc)
    provider = _provider_at(now)
    slots = provider.free_slots("Mars/Olympus", start=now, end=datetime(2026, 5, 18, 23, 0, tzinfo=timezone.utc))
    assert slots[0].start.hour == 9  # UTC fallback
