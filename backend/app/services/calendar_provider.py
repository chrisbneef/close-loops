"""Calendar abstraction.

Phase 3a ships a StubCalendarProvider that hard-codes the user's working hours
(weekday mornings + afternoons in their local timezone). Phase 4 swaps in a
real Google Calendar provider via MCP; the packer only ever talks to this
interface, so the swap is local.

A "free slot" is a contiguous (start, end) window in UTC. Slots returned by
this provider exclude blocks already on the user's calendar (in Phase 4) — the
stub assumes a completely empty calendar.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Protocol


@dataclass(frozen=True)
class FreeSlot:
    start: datetime  # tz-aware UTC
    end: datetime    # tz-aware UTC

    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class CalendarProvider(Protocol):
    def free_slots(self, user_timezone: str, *, start: datetime, end: datetime) -> list[FreeSlot]: ...


# Default work windows (local time): morning + afternoon, weekdays only.
DEFAULT_MORNING = (time(9, 0), time(12, 0))
DEFAULT_AFTERNOON = (time(13, 0), time(17, 0))


class StubCalendarProvider:
    """Returns 9:00-12:00 + 13:00-17:00 in the user's local tz, weekdays only.

    Skips slots that have already passed at call time, so the schedule starts
    from "now" rather than the start of today's morning block."""

    def __init__(
        self,
        morning: tuple[time, time] = DEFAULT_MORNING,
        afternoon: tuple[time, time] = DEFAULT_AFTERNOON,
        *,
        clock: callable = None,  # injection point for tests
    ):
        self.morning = morning
        self.afternoon = afternoon
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def free_slots(self, user_timezone: str, *, start: datetime, end: datetime) -> list[FreeSlot]:
        try:
            tz = zoneinfo.ZoneInfo(user_timezone or "UTC")
        except zoneinfo.ZoneInfoNotFoundError:
            tz = zoneinfo.ZoneInfo("UTC")

        now = self._clock()
        start = max(_as_utc(start), now)
        end = _as_utc(end)
        if start >= end:
            return []

        slots: list[FreeSlot] = []
        # Walk day by day in the user's local tz.
        cursor = start.astimezone(tz).date()
        last_day = end.astimezone(tz).date()
        while cursor <= last_day:
            if cursor.weekday() < 5:  # Mon..Fri
                for win_start, win_end in (self.morning, self.afternoon):
                    s_local = datetime.combine(cursor, win_start).replace(tzinfo=tz)
                    e_local = datetime.combine(cursor, win_end).replace(tzinfo=tz)
                    s_utc = s_local.astimezone(timezone.utc)
                    e_utc = e_local.astimezone(timezone.utc)
                    # Clip to the requested [start, end] window.
                    s_utc = max(s_utc, start)
                    e_utc = min(e_utc, end)
                    if s_utc < e_utc:
                        slots.append(FreeSlot(start=s_utc, end=e_utc))
            cursor += timedelta(days=1)
        return slots


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
