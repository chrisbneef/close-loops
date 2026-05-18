"""Pydantic v2 schemas for the /ingest pipeline.

The LLM-output schemas (`LLMTask`, `LLMDecomposition`) are passed verbatim to
`client.messages.parse(output_format=...)` so Claude returns validated objects
instead of free-form JSON we have to defensively parse.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMTask(BaseModel):
    """One micro-task in the decomposition."""

    title: str = Field(..., min_length=3, max_length=120, description="Short, action-oriented title (verb first).")
    est_minutes: int = Field(
        ...,
        ge=5,
        le=120,
        description="Estimated focused minutes. Bias small — most tasks should be 10–25 min.",
    )
    importance: int = Field(..., ge=1, le=10, description="Strategic importance 1–10.")
    depends_on: list[str] = Field(
        default_factory=list,
        description=(
            "Titles of OTHER tasks in this same output that must finish first. "
            "Use the exact title strings. Empty list if no prerequisites."
        ),
    )
    suggested_owner: Literal["self", "partner", "contractor"] = Field(
        "self",
        description=(
            "Who should own this. 'self' = the person who typed the goal; "
            "'partner' = the other co-founder; 'contractor' = needs to be hired/delegated outside the team."
        ),
    )


class LLMDecomposition(BaseModel):
    """The full structured output from Claude. `reasoning` comes first so Claude
    plans before committing to scores (per the spec's prompt scaffolding)."""

    reasoning: str = Field(
        ...,
        min_length=20,
        description="Brief step-by-step explanation of how you broke the goal down, before listing tasks.",
    )
    goal_deadline: Optional[datetime] = Field(
        None,
        description=(
            "If the goal mentions or implies a deadline (explicit date like 'June 1', "
            "or a relative phrase like 'by EOQ', 'before next Tuesday', 'end of month'), "
            "populate this as a timezone-aware ISO 8601 datetime in the requester's "
            "timezone (provided in the user message). Use 18:00:00 (end of business day) "
            "if only a calendar date is given. Leave null if no deadline is mentioned or "
            "reasonably implied."
        ),
    )
    tasks: list[LLMTask] = Field(..., min_length=1, max_length=25)


class IngestRequest(BaseModel):
    """POST /ingest body."""

    raw_goal: str = Field(..., min_length=5, max_length=2000)
    project_id: Optional[int] = None
    owner_id: Optional[int] = Field(
        None,
        description="User the request comes from. If omitted, defaults to the first cofounder in the DB (dev convenience).",
    )


class TaskOut(BaseModel):
    """Slim task representation in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    owner_id: int
    delegator_id: Optional[int] = None
    est_minutes: int
    importance: int
    status: str
    deadline: Optional[datetime] = None


class ScheduledBlockOut(BaseModel):
    task_id: int
    title: str
    start: datetime
    end: datetime
    priority: float


class ScheduleResponse(BaseModel):
    owner_id: int
    generated_at: datetime
    horizon_days: int
    blocks: list[ScheduledBlockOut]
    unscheduled_task_ids: list[int] = Field(
        default_factory=list,
        description="Tasks that didn't fit before the horizon — either capacity-exhausted or blocked by an unscheduled prereq.",
    )


class NextActionResponse(BaseModel):
    """Response for GET /next-action — what the user should do RIGHT NOW.

    `current` is the single next task (None if owner has nothing scheduled).
    `up_next` shows the next 2 in calendar order, dimmed in the UI."""

    current: Optional[TaskOut] = None
    current_start: Optional[datetime] = Field(
        None, description="When this task is scheduled to start (UTC)."
    )
    current_end: Optional[datetime] = Field(
        None, description="When this task is scheduled to end (UTC)."
    )
    why: Optional[str] = Field(
        None,
        description="One-line human-readable reason this is the next action (e.g. 'soonest scheduled block').",
    )
    up_next: list[TaskOut] = Field(
        default_factory=list,
        description="The next 1-2 tasks after `current`, in calendar order.",
    )


class ReportRow(BaseModel):
    """One completed task in the report window."""

    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    importance: int
    estimated_minutes: int
    actual_minutes: int
    deadline: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    started_at: datetime
    finished_at: datetime
    on_time: Optional[bool] = Field(
        None,
        description="True if finished_at <= deadline. None when the task had no deadline.",
    )
    over_estimate_ratio: float = Field(
        ...,
        description="actual_minutes / estimated_minutes. 1.0 = on estimate, 1.5 = 50% over.",
    )


class WeeklyReport(BaseModel):
    owner_id: int
    start_date: datetime
    end_date: datetime
    total_completed: int
    completed_on_time: int = Field(0, description="finished_at <= deadline")
    completed_late: int = Field(0, description="finished_at > deadline")
    no_deadline: int = Field(0, description="tasks completed but no deadline was set")
    avg_actual_over_est: Optional[float] = Field(
        None,
        description="Mean of actual_minutes / estimated_minutes across the window. None if no tasks.",
    )
    total_minutes_estimated: int = 0
    total_minutes_actual: int = 0
    longest_overrun: Optional[ReportRow] = Field(
        None, description="Task with the biggest (actual - estimated) delta in the window."
    )
    by_importance: dict[int, dict[str, int]] = Field(
        default_factory=dict,
        description=(
            "{importance: {'completed': n, 'on_time': n, 'late': n}}. "
            "Helps see whether high-importance work is actually getting done on time."
        ),
    )
    rows: list[ReportRow] = Field(default_factory=list, description="All completed tasks in the window, newest first.")


class IngestResponse(BaseModel):
    project_id: Optional[int]
    owner_id: int
    tasks: list[TaskOut]
    dependency_edges: list[tuple[int, int]] = Field(
        default_factory=list,
        description="(task_id, depends_on_task_id) pairs actually inserted.",
    )
    dropped_edges: list[tuple[str, str]] = Field(
        default_factory=list,
        description="(title, title) edges dropped to keep the DAG acyclic.",
    )
    temporal_correction_factor: float = Field(
        ...,
        description="Ratio applied to LLM est_minutes for this owner (1.0 = no historical data yet).",
    )
    reasoning: str
