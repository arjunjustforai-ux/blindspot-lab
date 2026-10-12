from app.services.knowledge.graph import ancestors, is_acyclic, topological_order, would_create_cycle

EDGES = [("revenue", "contribution"), ("contribution", "roas"), ("contribution", "cac_clv")]


def test_cycle_detection():
    assert would_create_cycle(EDGES, ("roas", "revenue"))
    assert would_create_cycle(EDGES, ("roas", "roas"))
    assert not would_create_cycle(EDGES, ("revenue", "roas"))


def test_topological_order_respects_prerequisites():
    order = topological_order(["roas", "cac_clv", "contribution", "revenue"], EDGES)
    assert order.index("revenue") < order.index("contribution") < order.index("roas")


def test_cyclic_graph_rejected():
    assert is_acyclic(["a", "b"], [("a", "b")])
    assert not is_acyclic(["a", "b"], [("a", "b"), ("b", "a")])


def test_ancestors():
    assert ancestors("roas", EDGES) == {"contribution", "revenue"}
    assert ancestors("revenue", EDGES) == set()
