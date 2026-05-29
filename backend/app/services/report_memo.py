"""Memo-style narrative for a daily/weekly report. Same warm-and-direct voice as
the morning briefing, but retrospective: what got done, what slipped, and the
biggest distraction. Sonnet 4.6 (summarization, recurring cost — Opus is overkill).

`generate_memo` calls Claude; `fallback_memo` is a deterministic template the
router uses when ANTHROPIC_API_KEY isn't set or the call fails, so the report
endpoint always returns *something* readable.
"""

from __future__ import annotations

import logging
from typing import Optional

import anthropic

from app.config import settings
from app.schemas import PeriodReport
from app.services.llm import LLMNotConfigured

logger = logging.getLogger(__name__)

MEMO_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """\
You are Cadence writing a short retrospective memo for a co-founder whose
cognitive profile is high ideation, low task initiation. You're summarizing
their DAY or their WEEK from the data provided.

Structure the memo with these beats (use short bold-ish lead-ins, not headings):
1. What they accomplished — name the standout items, celebrate real wins, never
   patronize. If nothing was completed, say so plainly and kindly.
2. What didn't get done — name the items that slipped (overdue / scheduled but
   unfinished). Be matter-of-fact, not scolding. This system rewards momentum,
   not guilt.
3. Their biggest distraction — if there were pauses, name the top reason and the
   count; tie it to a gentle observation. Skip if there were no pauses.
4. One forward-looking nudge — the single most useful thing to carry into
   tomorrow / next week.

Tone: warm, direct, no fluff, no emoji, no hedging. Like a sharp chief of staff
who read the data and respects the human. 4-7 sentences. Output the memo text
only — no greeting, no signoff.
"""


def _bullet(items: list[str]) -> str:
    return "\n".join(f"  - {i}" for i in items) if items else "  (none)"


def _format_for_prompt(report: PeriodReport, owner_name: str) -> str:
    period = "DAY" if report.granularity == "daily" else "WEEK"
    completed = [
        f"{r.title} (importance {r.importance}, {r.actual_minutes}m"
        + (", on time" if r.on_time else (", LATE" if r.on_time is False else ""))
        + ")"
        for r in report.rows
    ]
    incomplete = [
        f"{r.title} (importance {r.importance}" + (", OVERDUE" if r.overdue else "") + ")"
        for r in report.incomplete
    ]
    decayed = [f"{r.title}" for r in report.decayed]
    pause_lines = [f"{reason} ×{n}" for reason, n in report.pause_reasons.items()]

    lines = [
        f"Person: {owner_name}",
        f"Report type: {period}",
        f"Window: {report.start_date.date()} → {report.end_date.date()}",
        "",
        f"COMPLETED ({report.total_completed}; on-time {report.completed_on_time}, "
        f"late {report.completed_late}, no-deadline {report.no_deadline}):",
        _bullet(completed),
        "",
        f"DID NOT GET DONE ({len(report.incomplete)}):",
        _bullet(incomplete),
        "",
        f"DECAYED/ABANDONED ({len(report.decayed)}):",
        _bullet(decayed),
        "",
        f"PAUSES ({report.total_pauses} total, {report.total_pause_minutes} min; "
        f"biggest distraction: {report.biggest_distraction or 'none'}):",
        _bullet(pause_lines),
        "",
        f"Write the {period.lower()} memo.",
    ]
    return "\n".join(lines)


def generate_memo(
    report: PeriodReport, owner_name: str, *, client: Optional[anthropic.Anthropic] = None
) -> str:
    if client is None:
        if not settings.anthropic_api_key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY required for report memos.")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=MEMO_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _format_for_prompt(report, owner_name)}],
    )
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    text = "\n".join(parts).strip()
    logger.info(
        "report memo generated owner=%s granularity=%s tokens_out=%s",
        owner_name, report.granularity, response.usage.output_tokens,
    )
    return text


def fallback_memo(report: PeriodReport, owner_name: str) -> str:
    """Deterministic memo when the LLM isn't available — so the endpoint never
    returns a null memo just because the key is missing."""
    period = "today" if report.granularity == "daily" else "this week"
    parts: list[str] = []

    if report.total_completed:
        late = f" ({report.completed_late} late)" if report.completed_late else ""
        parts.append(
            f"You completed {report.total_completed} task"
            f"{'s' if report.total_completed != 1 else ''} {period}{late}."
        )
    else:
        parts.append(f"Nothing was logged as completed {period} yet.")

    if report.incomplete:
        overdue = sum(1 for r in report.incomplete if r.overdue)
        od = f", {overdue} overdue" if overdue else ""
        parts.append(f"{len(report.incomplete)} task{'s' if len(report.incomplete) != 1 else ''} didn't get done{od}.")

    if report.total_pauses:
        parts.append(
            f"You paused {report.total_pauses} time"
            f"{'s' if report.total_pauses != 1 else ''}"
            + (f"; biggest distraction: {report.biggest_distraction}." if report.biggest_distraction else ".")
        )

    return " ".join(parts)
