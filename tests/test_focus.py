"""Tests for task-aware budgeted retrieval (query.focus)."""

from __future__ import annotations

from second_brain import query
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _g() -> Graph:
    g = Graph(project="t")
    g.add_node(Node(id="src/auth_login.py", type=NodeType.PROGRAM, label="auth_login.py",
                    path="src/auth_login.py"))
    g.add_node(Node(id="src/auth_token.py", type=NodeType.PROGRAM, label="auth_token.py",
                    path="src/auth_token.py"))
    g.add_node(Node(id="src/unrelated.py", type=NodeType.PROGRAM, label="unrelated.py",
                    path="src/unrelated.py"))
    g.add_node(Node(id="area:src", type=NodeType.AREA, label="src"))
    g.add_edge(Edge("src/auth_login.py", "src/auth_token.py", EdgeType.IMPORTS))
    g.add_edge(Edge("src/unrelated.py", "src/auth_token.py", EdgeType.IMPORTS))
    return g


def setup_function() -> None:
    query.clear_focus_cache()


def test_seeds_match_task_tokens():
    res = query.focus(_g(), "auth login", budget_tokens=2000)
    assert not res["fallback"]
    assert "src/auth_login.py" in res["seeds"]
    assert "src/unrelated.py" not in res["seeds"]


def test_fallback_when_no_match():
    res = query.focus(_g(), "zzzznothing", budget_tokens=2000)
    assert res["fallback"] is True
    assert res["seeds"] == []
    assert res["nodes"]  # still returns globally important nodes


def test_budget_caps_nodes():
    tiny = query.focus(_g(), "auth", budget_tokens=1)
    # budget of 1 token still returns at least one node (the top anchor), never an empty answer.
    assert len(tiny["nodes"]) == 1
    big = query.focus(_g(), "auth", budget_tokens=10000)
    assert len(big["nodes"]) >= len(tiny["nodes"])
    assert tiny["token_estimate"] <= 10000


def test_areas_excluded_from_focus():
    res = query.focus(_g(), "src", budget_tokens=5000)
    assert all(n["type"] != "area" for n in res["nodes"])


def test_edges_are_knowledge_edges_among_chosen():
    res = query.focus(_g(), "auth", budget_tokens=5000)
    ids = {n["id"] for n in res["nodes"]}
    for e in res["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert e["type"] in ("imports", "references")


def test_cache_no_structural_collision():
    # Two graphs with the SAME project/node/edge counts but DIFFERENT structure must not
    # collide in the cache (regression: keying on len(edges) served stale scores).
    g1 = Graph(project="p")
    g2 = Graph(project="p")
    for g in (g1, g2):
        for x in ("a", "b", "c"):
            g.add_node(Node(id=x, type=NodeType.PROGRAM, label=x, path=x))
    g1.add_edge(Edge("a", "b", EdgeType.IMPORTS))
    g1.add_edge(Edge("a", "c", EdgeType.IMPORTS))
    g2.add_edge(Edge("a", "c", EdgeType.IMPORTS))
    g2.add_edge(Edge("b", "c", EdgeType.IMPORTS))
    query.clear_focus_cache()
    r1 = {n["id"]: n["score"] for n in query.focus(g1, "zz", budget_tokens=9999)["nodes"]}
    r2 = {n["id"]: n["score"] for n in query.focus(g2, "zz", budget_tokens=9999)["nodes"]}
    # In g2 both a and b point to c -> c strictly more important than in g1.
    assert r2["c"] > r1["c"]


def test_cache_is_bounded():
    g = _g()
    query.clear_focus_cache()
    for i in range(query._FOCUS_CACHE_MAX + 50):
        query.focus(g, f"task{i}", budget_tokens=100)
    assert len(query._FOCUS_CACHE) <= query._FOCUS_CACHE_MAX


def test_cache_used_and_clearable():
    g = _g()
    query.focus(g, "auth", budget_tokens=2000)
    assert query._FOCUS_CACHE  # populated
    query.clear_focus_cache()
    assert not query._FOCUS_CACHE
    # still works after clearing
    assert query.focus(g, "auth", budget_tokens=2000)["nodes"]
