from app.services.cycles import partition_acyclic


def test_drops_direct_two_cycle():
    accepted, dropped = partition_acyclic(["A", "B"], [("A", "B"), ("B", "A")])
    assert accepted == [("A", "B")]
    assert dropped == [("B", "A")]


def test_drops_three_cycle():
    accepted, dropped = partition_acyclic(
        ["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")]
    )
    assert accepted == [("A", "B"), ("B", "C")]
    assert dropped == [("C", "A")]


def test_keeps_linear_chain():
    edges = [("A", "B"), ("B", "C"), ("C", "D")]
    accepted, dropped = partition_acyclic(["A", "B", "C", "D"], edges)
    assert accepted == edges
    assert dropped == []


def test_keeps_diamond():
    # A→B, A→C, B→D, C→D is a DAG.
    edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
    accepted, dropped = partition_acyclic(["A", "B", "C", "D"], edges)
    assert accepted == edges
    assert dropped == []


def test_drops_self_edge():
    accepted, dropped = partition_acyclic(["A"], [("A", "A")])
    assert accepted == []
    assert dropped == [("A", "A")]


def test_drops_unknown_node_edge():
    accepted, dropped = partition_acyclic(["A", "B"], [("A", "Z"), ("A", "B")])
    assert accepted == [("A", "B")]
    assert dropped == [("A", "Z")]


def test_dedupes_repeated_edge():
    accepted, dropped = partition_acyclic(["A", "B"], [("A", "B"), ("A", "B")])
    assert accepted == [("A", "B")]
    assert dropped == [("A", "B")]
