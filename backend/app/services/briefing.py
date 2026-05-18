"""Daily briefing generator. Gathers yesterday's completions + today's top
scheduled tasks + streak info, then has Claude write a short conversational
summary in the tone the spec asks for: warm, direct, bias toward the most
important thing first.

Sonnet 4.6 (not Opus) because briefings are a daily recurring cost and
summarization is well within Sonnet's range. /ingest stays on Opus 4.7
where decomposition intelligence matters more.
"""

from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CalendarBlock, ExecutionLog, GamificationState, Task, User
from app.services.llm import LLMNotConfigured

logger = logging.getLogger(__name__)

BRIEFING_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """\
You are Cadence's morning briefing voice for a co-founder whose cognitive
profile is high ideation, low task initiation. Your job is to start their
day with a 3-5 sentence message that:

1. Surfaces the SINGLE most important thing to do today, by name, first.
2. Acknowledges what they completed yesterday — celebrate small wins, but
   never patronize.
3. Calls out anything urgent (deadline today/tomorrow) without alarming.
4. Mentions the streak only if it adds momentum (e.g. "your 3-day streak
   continues"); skip if 0 or 1.

Tone: warm, direct, no fluff, no emoji, no hedging. Write like a sharp
chief of staff who's read the data and knows the human. The reader opens
this message with their morning coffee — make them feel ready to begin,
not overwhelmed.

Output the message text only — no greeting, no signoff, no "Good morning"
boilerplate. Just the 3-5 sentences.
"""


@dataclass
class BriefingData:
    """All the inputs that go to Claude for the briefing. Kept separate so
    tests can construct it directly without seeding a DB."""

    requester_name: str
    requester_timezone: str
    today_local: str  # ISO date
    yesterday_completed: list[dict]  # [{title, est_minutes, actual_minutes, on_time}]
    today_scheduled: list[dict]      # [{title, importance, est_minutes, start_local, deadline}]
    current_streak: int
    longest_streak: int


def gather(session: Session, owner: User, *, now: Optional[datetime] = None) -> BriefingData:
    """Pull the raw inputs for `owner`'s briefing from the DB."""
    now = now or datetime.now(timezone.utc)
    try:
        tz = zoneinfo.ZoneInfo(owner.timezone or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        tz = zoneinfo.ZoneInfo("UTC")

    today_local = now.astimezone(tz).date()
    yesterday_local = today_local - timedelta(days=1)

    # Yesterday's completions for this owner.
    yest_start_utc = datetime.combine(yesterday_local, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    yest_end_utc = datetime.combine(today_local, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    yesterday_rows = list(session.execute(
        select(ExecutionLog, Task)
        .join(Task, Task.id == ExecutionLog.task_id)
        .where(
            ExecutionLog.user_id == owner.id,
            ExecutionLog.finished_at >= yest_start_utc,
            ExecutionLog.finished_at < yest_end_utc,
        )
        .order_by(ExecutionLog.finished_at.asc())
    ).all())
    yesterday_completed = []
    for log, task in yesterday_rows:
        deadline = task.deadline
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        finished_at = log.finished_at if log.finished_at.tzinfo else log.finished_at.replace(tzinfo=timezone.utc)
        on_time = None if deadline is None else (finished_at <= deadline)
        yesterday_completed.append({
            "title": task.title,
            "est_minutes": log.estimated_minutes,
            "actual_minutes": log.actual_minutes,
            "on_time": on_time,
            "importance": task.importance,
        })

    # Today's scheduled work — calendar_blocks starting today (in owner tz).
    today_start_utc = yest_end_utc
    tomorrow_start_utc = today_start_utc + timedelta(days=1)
    today_rows = list(session.execute(
        select(CalendarBlock, Task)
        .join(Task, Task.id == CalendarBlock.task_id)
        .where(
            Task.owner_id == owner.id,
            Task.status.in_(("pending", "scheduled", "in_progress")),
            CalendarBlock.start >= today_start_utc,
            CalendarBlock.start < tomorrow_start_utc,
        )
        .order_by(CalendarBlock.start.asc())
        .limit(8)
    ).all())
    today_scheduled = []
    for block, task in today_rows:
        start = block.start if block.start.tzinfo else block.start.replace(tzinfo=timezone.utc)
        deadline = task.deadline
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        today_scheduled.append({
            "title": task.title,
            "importance": task.importance,
            "est_minutes": task.est_minutes,
            "start_local": start.astimezone(tz).strftime("%-I:%M %p"),
            "deadline_iso": deadline.isoformat() if deadline else None,
        })

    state = session.get(GamificationState, owner.id)
    current_streak = state.current_streak if state else 0
    longest_streak = state.longest_streak if state else 0

    return BriefingData(
        requester_name=owner.name,
        requester_timezone=tz.key,
        today_local=today_local.isoformat(),
        yesterday_completed=yesterday_completed,
        today_scheduled=today_scheduled,
        current_streak=current_streak,
        longest_streak=longest_streak,
    )


def _format_for_prompt(data: BriefingData) -> str:
    """Turn the structured BriefingData into the user-message body for Claude."""
    lines = [
        f"Requester: {data.requester_name} ({data.requester_timezone})",
        f"Today: {data.today_local}",
        f"Streak: {data.current_streak} days (longest ever: {data.longest_streak})",
        "",
    ]
    if data.yesterday_completed:
        lines.append("YESTERDAY (completed):")
        for t in data.yesterday_completed:
            on_time = "✓" if t["on_time"] is True else ("late" if t["on_time"] is False else "")
            ratio = t["actual_minutes"] / max(t["est_minutes"], 1)
            lines.append(f"  - {t['title']} (importance {t['importance']}, est {t['est_minutes']}m, actual {t['actual_minutes']}m, {ratio:.1f}x estimate) {on_time}")
    else:
        lines.append("YESTERDAY: nothing logged.")
    lines.append("")
    if data.today_scheduled:
        lines.append("TODAY (scheduled, in order):")
        for t in data.today_scheduled:
            dl = f" — due {t['deadline_iso'][:10]}" if t["deadline_iso"] else ""
            lines.append(f"  - {t['start_local']}  {t['title']} (importance {t['importance']}, est {t['est_minutes']}m){dl}")
    else:
        lines.append("TODAY: nothing scheduled.")
    lines.append("")
    lines.append("Write the briefing.")
    return "\n".join(lines)


def generate(data: BriefingData, *, client: Optional[anthropic.Anthropic] = None) -> str:
    """Call Claude with the briefing data; return the message text."""
    if client is None:
        if not settings.anthropic_api_key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY required for briefings.")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=BRIEFING_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _format_for_prompt(data)}],
    )
    # Concatenate any text blocks (adaptive thinking may emit thinking blocks first).
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    text = "\n".join(parts).strip()
    logger.info(
        "briefing generated requester=%s tokens_in=%s tokens_out=%s",
        data.requester_name, response.usage.input_tokens, response.usage.output_tokens,
    )
    return text
