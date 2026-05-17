"""Compute momentum weight per task — how many other tasks depend on it.

For Phase 3a we use the **direct dependents** count (one hop) — simple, cheap,
and aligned with the spec's "# of downstream blocked tasks". Transitive reach
is a clean upgrade later if scheduling quality demands it.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaskDependency


def momentum_by_task(session: Session, task_ids: list[int]) -> dict[int, int]:
    """For each task in `task_ids`, returns the count of other tasks that
    directly depend on it. Tasks with no dependents map to 0."""
    if not task_ids:
        return {}
    rows = session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.depends_on_task_id.in_(task_ids)
        )
    ).all()
    counts = Counter(row[0] for row in rows)
    return {tid: counts.get(tid, 0) for tid in task_ids}


def dependencies_by_task(session: Session, task_ids: list[int]) -> dict[int, list[int]]:
    """For each task in `task_ids`, returns the list of task IDs it depends on
    (its prerequisites). Used by the packer to enforce DAG ordering."""
    if not task_ids:
        return {}
    rows = session.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id.in_(task_ids)
        )
    ).all()
    deps: dict[int, list[int]] = {tid: [] for tid in task_ids}
    for task_id, dep_id in rows:
        deps[task_id].append(dep_id)
    return deps
