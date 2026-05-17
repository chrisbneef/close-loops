"""End-to-end ingest pipeline: raw_goal → LLM decomposition → temporal
correction → owner routing → cycle-safe persistence → reschedule trigger.

The router is a thin shell around `ingest()`. Keeping the orchestration in a
service module makes the pipeline straightforward to unit-test against an
in-memory SQLite + a stubbed Anthropic client.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Task, TaskDependency, User
from app.schemas import IngestResponse, LLMDecomposition, LLMTask, TaskOut
from app.services import cycles, llm, reschedule, temporal

logger = logging.getLogger(__name__)


def _resolve_owner(session: Session, requested_owner_id: Optional[int]) -> User:
    """Use the requested owner, or fall back to the first cofounder (dev convenience)."""
    if requested_owner_id is not None:
        owner = session.get(User, requested_owner_id)
        if owner is None:
            raise ValueError(f"owner_id={requested_owner_id} does not exist")
        return owner
    owner = session.execute(select(User).where(User.role == "cofounder").order_by(User.id).limit(1)).scalar_one_or_none()
    if owner is None:
        raise ValueError("No cofounder user exists; seed users first or pass owner_id explicitly.")
    return owner


def _resolve_partner(session: Session, owner: User) -> Optional[User]:
    """The other cofounder, if any. Used to route suggested_owner='partner'."""
    return session.execute(
        select(User).where(User.role == "cofounder", User.id != owner.id).order_by(User.id).limit(1)
    ).scalar_one_or_none()


def _resolve_project(session: Session, project_id: Optional[int]) -> Optional[Project]:
    if project_id is None:
        return None
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"project_id={project_id} does not exist")
    return project


def _route_owner(
    suggested: str, requester: User, partner: Optional[User]
) -> tuple[int, Optional[int]]:
    """Map LLM suggested_owner → (owner_id, delegator_id).

    - "self" → owner=requester, no delegator
    - "partner" → owner=partner if available, else owner=requester
    - "contractor" → owner=requester (until delegation graph routes it), delegator=requester
    """
    if suggested == "partner" and partner is not None:
        return partner.id, requester.id
    if suggested == "contractor":
        return requester.id, requester.id
    return requester.id, None


def ingest(
    session: Session,
    *,
    raw_goal: str,
    owner_id: Optional[int] = None,
    project_id: Optional[int] = None,
    anthropic_client: anthropic.Anthropic | None = None,
    llm_override: LLMDecomposition | None = None,
) -> IngestResponse:
    """Run the full pipeline. `llm_override` lets tests skip the network call."""
    requester = _resolve_owner(session, owner_id)
    partner = _resolve_partner(session, requester)
    project = _resolve_project(session, project_id)

    decomposition: LLMDecomposition = llm_override or llm.decompose(
        raw_goal,
        owner_name=requester.name,
        owner_timezone=requester.timezone,
        partner_name=partner.name if partner else None,
        project_context=project.north_star if project else None,
        client=anthropic_client,
    )

    # Normalize the (optional) goal deadline to timezone-aware UTC for storage.
    goal_deadline = decomposition.goal_deadline
    if goal_deadline is not None and goal_deadline.tzinfo is None:
        logger.warning("LLM emitted naive datetime; treating as UTC: %s", goal_deadline)
        goal_deadline = goal_deadline.replace(tzinfo=timezone.utc)

    factor = temporal.correction_factor(session, requester.id)
    logger.info("temporal correction factor for user=%s: %.2f", requester.id, factor)

    # Cycle-safe edges (on titles, before insert).
    titles = [t.title for t in decomposition.tasks]
    raw_edges: list[tuple[str, str]] = [
        (t.title, dep) for t in decomposition.tasks for dep in t.depends_on
    ]
    accepted_title_edges, dropped_title_edges = cycles.partition_acyclic(titles, raw_edges)

    # Persist tasks, mapping title -> id for the edge insert.
    title_to_id: dict[str, int] = {}
    inserted: list[Task] = []
    for ltask in decomposition.tasks:
        owner_id_for_task, delegator_id = _route_owner(ltask.suggested_owner, requester, partner)
        task = Task(
            project_id=project.id if project else None,
            title=ltask.title,
            owner_id=owner_id_for_task,
            delegator_id=delegator_id,
            est_minutes=temporal.apply_correction(ltask.est_minutes, factor),
            importance=ltask.importance,
            deadline=goal_deadline,  # uniform per-task deadline; scheduler derives finer ordering from the DAG
            status="pending",
        )
        session.add(task)
        session.flush()  # populate task.id
        title_to_id[ltask.title] = task.id
        inserted.append(task)

    dependency_edges: list[tuple[int, int]] = []
    for src_title, dst_title in accepted_title_edges:
        edge = TaskDependency(
            task_id=title_to_id[src_title], depends_on_task_id=title_to_id[dst_title]
        )
        session.add(edge)
        dependency_edges.append((edge.task_id, edge.depends_on_task_id))

    session.commit()
    for t in inserted:
        session.refresh(t)

    reschedule.request_reschedule_for_owner(requester.id, reason=f"ingest: {len(inserted)} new tasks")

    return IngestResponse(
        project_id=project.id if project else None,
        owner_id=requester.id,
        tasks=[TaskOut.model_validate(t) for t in inserted],
        dependency_edges=dependency_edges,
        dropped_edges=dropped_title_edges,
        temporal_correction_factor=factor,
        reasoning=decomposition.reasoning,
    )
