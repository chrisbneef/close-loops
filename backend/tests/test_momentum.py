from app import models
from app.services.momentum import dependencies_by_task, momentum_by_task


def _seed(session, michael, edges: list[tuple[int, int]], n: int):
    """Insert n placeholder tasks for michael, then add the (task_id, depends_on_task_id) edges."""
    tasks = [models.Task(title=f"T{i}", owner_id=michael.id, est_minutes=15) for i in range(n)]
    session.add_all(tasks)
    session.flush()
    ids = [t.id for t in tasks]
    for src_idx, dst_idx in edges:
        session.add(models.TaskDependency(task_id=ids[src_idx], depends_on_task_id=ids[dst_idx]))
    session.commit()
    return ids


def test_isolated_tasks_have_zero_momentum(session, cofounders):
    michael, _ = cofounders
    ids = _seed(session, michael, edges=[], n=3)
    m = momentum_by_task(session, ids)
    assert all(v == 0 for v in m.values())


def test_chain_momentum_only_counts_direct_dependents(session, cofounders):
    michael, _ = cofounders
    # T0 → T1 → T2  (T1 depends on T0; T2 depends on T1)
    ids = _seed(session, michael, edges=[(1, 0), (2, 1)], n=3)
    m = momentum_by_task(session, ids)
    assert m[ids[0]] == 1  # T1 depends on it
    assert m[ids[1]] == 1  # T2 depends on it
    assert m[ids[2]] == 0  # nothing depends on T2


def test_diamond_momentum(session, cofounders):
    michael, _ = cofounders
    # T0 has two direct dependents (T1, T2). T3 depends on both T1 and T2.
    # Direct dependents only — so T0 has momentum 2, T1+T2 have 1 each, T3 has 0.
    ids = _seed(session, michael, edges=[(1, 0), (2, 0), (3, 1), (3, 2)], n=4)
    m = momentum_by_task(session, ids)
    assert m[ids[0]] == 2
    assert m[ids[1]] == 1
    assert m[ids[2]] == 1
    assert m[ids[3]] == 0


def test_dependencies_by_task_returns_prereqs(session, cofounders):
    michael, _ = cofounders
    ids = _seed(session, michael, edges=[(1, 0), (2, 0), (2, 1)], n=3)
    deps = dependencies_by_task(session, ids)
    assert deps[ids[0]] == []
    assert deps[ids[1]] == [ids[0]]
    assert sorted(deps[ids[2]]) == sorted([ids[0], ids[1]])
