"""End-to-end ingest tests with the LLM stubbed via the `llm_override` hatch.

These cover owner routing, cycle dropping, dependency persistence, and the
temporal correction integration — without touching the network.
"""

from app import models
from app.schemas import LLMDecomposition, LLMTask
from app.services.decomposition import ingest


def _decomp(*tasks: LLMTask, reasoning: str = "stub decomposition for testing") -> LLMDecomposition:
    return LLMDecomposition(reasoning=reasoning, tasks=list(tasks))


def test_happy_path_persists_tasks_and_edges(session, cofounders):
    michael, _ = cofounders
    decomp = _decomp(
        LLMTask(title="Draft outline", est_minutes=20, importance=9, depends_on=[]),
        LLMTask(title="Build deck", est_minutes=25, importance=7, depends_on=["Draft outline"]),
        LLMTask(title="Send invite", est_minutes=5, importance=6, depends_on=[]),
    )

    resp = ingest(session, raw_goal="ship the webinar", owner_id=michael.id, llm_override=decomp)

    assert len(resp.tasks) == 3
    assert resp.dropped_edges == []
    assert len(resp.dependency_edges) == 1
    titles = {t.title for t in resp.tasks}
    assert titles == {"Draft outline", "Build deck", "Send invite"}
    # The dependency edge points to "Draft outline" — verify that mapping is right.
    src_id, dst_id = resp.dependency_edges[0]
    src = session.get(models.Task, src_id)
    dst = session.get(models.Task, dst_id)
    assert src.title == "Build deck"
    assert dst.title == "Draft outline"


def test_routes_partner_owner_with_delegator(session, cofounders):
    michael, chris = cofounders
    decomp = _decomp(
        LLMTask(title="Self task", est_minutes=10, importance=5, suggested_owner="self"),
        LLMTask(title="Partner task", est_minutes=10, importance=5, suggested_owner="partner"),
    )

    resp = ingest(session, raw_goal="do stuff", owner_id=michael.id, llm_override=decomp)

    by_title = {t.title: t for t in resp.tasks}
    assert by_title["Self task"].owner_id == michael.id
    assert by_title["Self task"].delegator_id is None
    assert by_title["Partner task"].owner_id == chris.id
    assert by_title["Partner task"].delegator_id == michael.id


def test_contractor_assigns_self_but_flags_delegator(session, cofounders):
    michael, _ = cofounders
    decomp = _decomp(
        LLMTask(title="Mass data entry", est_minutes=10, importance=3, suggested_owner="contractor"),
    )

    resp = ingest(session, raw_goal="hire help", owner_id=michael.id, llm_override=decomp)

    task = resp.tasks[0]
    assert task.owner_id == michael.id
    assert task.delegator_id == michael.id


def test_drops_cyclic_dependency(session, cofounders):
    michael, _ = cofounders
    decomp = _decomp(
        LLMTask(title="Task alpha", est_minutes=10, importance=5, depends_on=["Task beta"]),
        LLMTask(title="Task beta", est_minutes=10, importance=5, depends_on=["Task alpha"]),
    )

    resp = ingest(session, raw_goal="cyclic input", owner_id=michael.id, llm_override=decomp)

    assert len(resp.dependency_edges) == 1
    assert len(resp.dropped_edges) == 1


def test_drops_dependency_on_unknown_task(session, cofounders):
    michael, _ = cofounders
    decomp = _decomp(
        LLMTask(title="Real task", est_minutes=10, importance=5, depends_on=["ghost task"]),
    )

    resp = ingest(session, raw_goal="unknown dep", owner_id=michael.id, llm_override=decomp)

    assert resp.dependency_edges == []
    assert resp.dropped_edges == [("Real task", "ghost task")]


def test_attaches_to_project_when_given(session, cofounders):
    michael, _ = cofounders
    project = models.Project(name="Q3 Launch", status="active")
    session.add(project)
    session.commit()

    decomp = _decomp(LLMTask(title="Lone task", est_minutes=10, importance=5))
    resp = ingest(session, raw_goal="goal goes here", owner_id=michael.id, project_id=project.id, llm_override=decomp)

    persisted = session.get(models.Task, resp.tasks[0].id)
    assert persisted.project_id == project.id


def test_unknown_owner_raises_value_error(session, cofounders):
    import pytest

    decomp = _decomp(LLMTask(title="Lone task", est_minutes=10, importance=5))
    with pytest.raises(ValueError, match="owner_id=999"):
        ingest(session, raw_goal="goal goes here", owner_id=999, llm_override=decomp)


def test_unknown_project_raises_value_error(session, cofounders):
    import pytest

    michael, _ = cofounders
    decomp = _decomp(LLMTask(title="Lone task", est_minutes=10, importance=5))
    with pytest.raises(ValueError, match="project_id=999"):
        ingest(session, raw_goal="goal goes here", owner_id=michael.id, project_id=999, llm_override=decomp)
