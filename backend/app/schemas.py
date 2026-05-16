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
