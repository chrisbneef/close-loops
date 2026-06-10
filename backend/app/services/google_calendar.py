"""GoogleCalendarProvider — implements the CalendarProvider Protocol against
the real Google Calendar API.

Strategy:
- Work-hours skeleton comes from StubCalendarProvider (9–12 + 13–17 weekdays
  in the owner's tz). On top of that we read the user's real calendar events
  and subtract them as busy intervals. Events we ourselves created (tagged
  `extendedProperties.private.cadence_block = "true"`) are skipped — they
  represent the schedule we're about to rebuild, not constraints.
- Writes go through events().insert/update/delete with the cadence_block tag
  so we can identify and never overwrite the user's real meetings.

One provider instance per (refresh_token, owner) — cheap to construct; the
Google credentials object handles access_token refresh internally on each call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.services.calendar_provider import CalendarEvent, FreeSlot, StubCalendarProvider

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CADENCE_BLOCK_PROPERTY = "cadence_block"
CADENCE_TASK_ID_PROPERTY = "cadence_task_id"


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Google Calendar responseStatus values the user counts as "attending":
# - accepted: explicit yes
# - tentative: marked maybe, still treated as busy
# Skipped (treated as free time + hidden from rail):
# - declined: explicit no
# - needsAction: no response (Google renders these as 'white' / uncolored —
#   exactly the case the user flagged when an unaccepted "RE Showing"
#   ate his 11:30 slot)
_ATTENDING_RESPONSES = frozenset({"accepted", "tentative"})


def _user_attending(event: dict) -> bool:
    """Whether the calendar's owner has signaled attendance for this event.

    Events with no attendees array — personal blocks the user created for
    themselves — are always considered attending. Events the user organized
    but didn't formally invite themselves to are also treated as attending."""
    attendees = event.get("attendees")
    if not attendees:
        return True
    for a in attendees:
        if a.get("self") is True:
            return a.get("responseStatus", "accepted") in _ATTENDING_RESPONSES
    return True


def _subtract_busy(
    slots: list[FreeSlot], busy: list[tuple[datetime, datetime]]
) -> list[FreeSlot]:
    """Carve busy intervals out of free slots. O(slots * busy); fine for our scale."""
    result = list(slots)
    for b_start, b_end in busy:
        b_start = _to_utc(b_start)
        b_end = _to_utc(b_end)
        next_result: list[FreeSlot] = []
        for s in result:
            if s.end <= b_start or s.start >= b_end:
                next_result.append(s)
                continue
            if b_start > s.start:
                next_result.append(FreeSlot(start=s.start, end=b_start))
            if b_end < s.end:
                next_result.append(FreeSlot(start=b_end, end=s.end))
        result = next_result
    return result


class GoogleCalendarProvider:
    """Production CalendarProvider. Constructed per-user from their refresh_token."""

    def __init__(self, refresh_token: str, calendar_id: str = "primary"):
        if not refresh_token:
            raise ValueError("GoogleCalendarProvider requires a non-empty refresh_token")
        self._refresh_token = refresh_token
        self.calendar_id = calendar_id
        self._stub = StubCalendarProvider()  # delegate for the work-hours skeleton
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = Credentials(
                token=None,
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                scopes=SCOPES,
            )
            creds.refresh(Request())
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def free_slots(
        self, user_timezone: str, *, start: datetime, end: datetime
    ) -> list[FreeSlot]:
        skeleton = self._stub.free_slots(user_timezone, start=start, end=end)
        if not skeleton:
            return []
        try:
            events = self._list_events(_to_utc(start), _to_utc(end))
        except Exception:
            logger.exception("Google Calendar list failed; falling back to skeleton (no busy filter)")
            return skeleton

        busy: list[tuple[datetime, datetime]] = []
        for ev in events:
            priv = (ev.get("extendedProperties") or {}).get("private", {})
            if priv.get(CADENCE_BLOCK_PROPERTY) == "true":
                continue  # our own previously-scheduled block — not a constraint
            if not _user_attending(ev):
                continue  # declined / no-response → don't block work time
            s = ev.get("start", {}).get("dateTime")
            e = ev.get("end", {}).get("dateTime")
            if not s or not e:
                continue  # skip all-day events for now
            busy.append((datetime.fromisoformat(s), datetime.fromisoformat(e)))
        return _subtract_busy(skeleton, busy)

    def events_for_window(
        self, user_timezone: str, *, start: datetime, end: datetime,
    ) -> list[CalendarEvent]:
        """Return real meetings (non-Cadence events) in [start, end] sorted by
        start time — used by the Day Plan timeline. All-day events are skipped
        since they don't anchor focused work."""
        try:
            raw = self._list_events(_to_utc(start), _to_utc(end))
        except Exception:
            logger.exception("Google Calendar list failed; returning no events")
            return []
        out: list[CalendarEvent] = []
        for ev in raw:
            priv = (ev.get("extendedProperties") or {}).get("private", {})
            if priv.get(CADENCE_BLOCK_PROPERTY) == "true":
                continue  # our own block — already shown via calendar_blocks
            if not _user_attending(ev):
                continue  # hide declined / unanswered invites from TODAY rail
            s = ev.get("start", {}).get("dateTime")
            e = ev.get("end", {}).get("dateTime")
            if not s or not e:
                continue  # skip all-day events
            out.append(CalendarEvent(
                start=datetime.fromisoformat(s),
                end=datetime.fromisoformat(e),
                title=ev.get("summary") or "(untitled meeting)",
            ))
        out.sort(key=lambda e: e.start)
        return out

    def _list_events(self, start: datetime, end: datetime) -> list[dict]:
        service = self._get_service()
        result = (
            service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
            )
            .execute()
        )
        return result.get("items", [])

    # ---- write operations (mirroring calendar_blocks to Google) ----

    def create_event(
        self, *, start: datetime, end: datetime, title: str, task_id: int
    ) -> str:
        body = {
            "summary": title,
            "description": f"Auto-scheduled by Cadence (task #{task_id}). Edits will be overwritten on the next tick.",
            "start": {"dateTime": _to_utc(start).isoformat()},
            "end": {"dateTime": _to_utc(end).isoformat()},
            "extendedProperties": {
                "private": {
                    CADENCE_BLOCK_PROPERTY: "true",
                    CADENCE_TASK_ID_PROPERTY: str(task_id),
                }
            },
            "transparency": "opaque",
            "reminders": {"useDefault": False},
        }
        service = self._get_service()
        created = service.events().insert(calendarId=self.calendar_id, body=body).execute()
        return created["id"]

    def update_event(
        self, *, event_id: str, start: datetime, end: datetime, title: str
    ) -> None:
        body = {
            "summary": title,
            "start": {"dateTime": _to_utc(start).isoformat()},
            "end": {"dateTime": _to_utc(end).isoformat()},
        }
        service = self._get_service()
        service.events().patch(calendarId=self.calendar_id, eventId=event_id, body=body).execute()

    def delete_event(self, *, event_id: str) -> None:
        service = self._get_service()
        try:
            service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        except Exception as e:
            # 410 (already deleted) or 404 (never existed): treat as success.
            status = getattr(getattr(e, "resp", None), "status", None)
            if status in (404, 410):
                logger.warning("delete_event no-op: event %s already gone", event_id)
                return
            raise
