"""
Section 3 schema. Kept in one module — the tables are tightly related and small,
and the scheduler reads across all of them on every tick.

Conventions:
- Time fields are timezone-aware UTC (`DateTime(timezone=True)`).
- Status fields are plain strings with a CHECK constraint — portable across SQLite
  (dev) and Postgres (prod) without coupling to Postgres ENUM types.
- `delegation_graph.materialized_path` is intentionally a path string like '1/2/4/'
  so subtree queries use `LIKE '1/%'` instead of recursive CTEs (per spec §3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


TASK_STATUSES = ("pending", "scheduled", "in_progress", "done", "decayed")
PROJECT_STATUSES = ("active", "paused", "done", "archived")
PRESENCE_STATUSES = ("focusing", "idle", "offline")
USER_ROLES = ("cofounder", "team", "contractor")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="cofounder")
    capacity_score: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    push_token: Mapped[Optional[str]] = mapped_column(String(255))
    # 24 hourly weights 0..1 — circadian load penalty input for the scheduler.
    energy_curve: Mapped[Optional[list]] = mapped_column(JSON)
    # Google OAuth (Phase 4) — email is the lookup key matching the OAuth grant;
    # google_refresh_token is what we exchange for short-lived access tokens.
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    google_refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"role IN {USER_ROLES!r}", name="ck_users_role"),
        CheckConstraint("capacity_score >= 0 AND capacity_score <= 100", name="ck_users_capacity_range"),
    )

    owned_tasks: Mapped[list["Task"]] = relationship("Task", foreign_keys="Task.owner_id", back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    north_star: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    hard_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (CheckConstraint(f"status IN {PROJECT_STATUSES!r}", name="ck_projects_status"),)

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    delegator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    est_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    # Recomputed every scheduler tick. Stored so the UI / queries can sort cheaply.
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # # of tasks blocked downstream by this one — populated by the scheduler.
    momentum_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # Fixed anchors: live webinars, dry-runs, scheduled email sends.
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUSES!r}", name="ck_tasks_status"),
        CheckConstraint("importance >= 1 AND importance <= 10", name="ck_tasks_importance_range"),
        CheckConstraint("est_minutes > 0", name="ck_tasks_est_positive"),
        Index("ix_tasks_status_priority", "status", "priority_score"),
        Index("ix_tasks_deadline", "deadline"),
        Index("ix_tasks_owner_status", "owner_id", "status"),
    )

    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="tasks")
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id], back_populates="owned_tasks")
    delegator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[delegator_id])
    blocks = relationship(
        "TaskDependency", foreign_keys="TaskDependency.depends_on_task_id", cascade="all, delete-orphan"
    )
    depends_on = relationship(
        "TaskDependency", foreign_keys="TaskDependency.task_id", cascade="all, delete-orphan"
    )


class TaskDependency(Base):
    """Edge in the task DAG. Cycle prevention is enforced in the ingest layer, not the DB."""

    __tablename__ = "task_dependencies"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        CheckConstraint("task_id <> depends_on_task_id", name="ck_taskdep_no_self_edge"),
    )


class DelegationGraph(Base):
    """Tree of who-delegates-to-whom, encoded as a materialized path so subtree
    queries are `LIKE '1/%'` instead of recursive CTEs (spec §3)."""

    __tablename__ = "delegation_graph"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    materialized_path: Mapped[str] = mapped_column(String(512), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_delegation_graph_user"),
        # The text_pattern_ops variant is added in the migration when running on
        # Postgres, so LIKE-prefix queries hit the index.
        Index("ix_delegation_graph_path", "materialized_path"),
    )


class CalendarBlock(Base):
    __tablename__ = "calendar_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    gcal_event_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("start < \"end\"", name="ck_calendar_block_time_order"),
        Index("ix_calendar_blocks_task", "task_id"),
        Index("ix_calendar_blocks_start", "start"),
    )


class GamificationState(Base):
    __tablename__ = "gamification_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unlocked_themes: Mapped[Optional[list]] = mapped_column(JSON, default=list)


class Presence(Base):
    __tablename__ = "presence"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="offline")
    current_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (CheckConstraint(f"status IN {PRESENCE_STATUSES!r}", name="ck_presence_status"),)


class ExecutionLog(Base):
    """Training data for the temporal-correction factor (Section 4 pipeline step 3)."""

    __tablename__ = "execution_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_execution_log_user", "user_id"),
        Index("ix_execution_log_task", "task_id"),
    )
