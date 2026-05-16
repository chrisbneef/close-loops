"""DAG cycle prevention for the ingest pipeline.

The LLM may emit a contradictory dependency (A depends on B, B depends on A).
We accept edges greedily; if adding one would create a cycle, we drop it and
keep going. The dropped edges are surfaced back to the caller for visibility.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable


def _reachable(adj: dict[str, set[str]], start: str, target: str) -> bool:
    """DFS: is `target` reachable from `start` in the given adjacency map?"""
    if start == target:
        return True
    visited: set[str] = set()
    stack: list[str] = [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adj.get(node, ()))
    return False


def partition_acyclic(
    nodes: Iterable[str], edges: Iterable[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Greedy: add each edge unless it would create a cycle.

    Edge convention: `(task, depends_on)` — task waits for depends_on. A cycle
    forms when, after adding `(a, b)`, there is already a path `b → ... → a`.

    Also drops:
    - self-edges (a, a)
    - edges referencing unknown nodes
    - duplicate edges

    Returns (accepted_edges, dropped_edges).
    """
    node_set = set(nodes)
    adj: dict[str, set[str]] = defaultdict(set)
    accepted: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for src, dst in edges:
        if (src, dst) in seen:
            dropped.append((src, dst))
            continue
        seen.add((src, dst))

        if src == dst or src not in node_set or dst not in node_set:
            dropped.append((src, dst))
            continue

        if _reachable(adj, dst, src):
            dropped.append((src, dst))
            continue

        adj[src].add(dst)
        accepted.append((src, dst))

    return accepted, dropped
