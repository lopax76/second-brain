"""Tests for upstream/downstream impact queries."""

from __future__ import annotations

import pytest

from second_brain import query
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _g() -> Graph:
    g = Graph(project="t")
    for nid in ("a.py", "b.py", "c.py", "d.py"):
        g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid, path=nid))
    # a -> b -> c  (a imports b, b imports c);  d -> b
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))
    g.add_edge(Edge("b.py", "c.py", EdgeType.IMPORTS))
    g.add_edge(Edge("d.py", "b.py", EdgeType.IMPORTS))
    return g


def test_impact_unknown_node():
    assert query.impact(_g(), "nope.py")["exists"] is False


def test_downstream_follows_outgoing():
    r = query.impact(_g(), "a.py", direction="down", max_depth=2)
    assert {e["id"] for e in r["downstream"][1]} == {"b.py"}
    assert {e["id"] for e in r["downstream"][2]} == {"c.py"}
    assert "upstream" not in r


def test_upstream_follows_incoming():
    r = query.impact(_g(), "b.py", direction="up", max_depth=1)
    assert {e["id"] for e in r["upstream"][1]} == {"a.py", "d.py"}
    assert "downstream" not in r


def test_both_directions():
    r = query.impact(_g(), "b.py", direction="both", max_depth=1)
    assert {e["id"] for e in r["upstream"][1]} == {"a.py", "d.py"}
    assert {e["id"] for e in r["downstream"][1]} == {"c.py"}


def test_depth_limit():
    r = query.impact(_g(), "a.py", direction="down", max_depth=1)
    assert set(r["downstream"]) == {1}  # depth 2 (c.py) not reached


def test_cap_truncates_per_depth():
    g = Graph(project="t")
    g.add_node(Node(id="hub.py", type=NodeType.PROGRAM, label="hub.py", path="hub.py"))
    for i in range(10):
        nid = f"dep{i}.py"
        g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid, path=nid))
        g.add_edge(Edge("hub.py", nid, EdgeType.IMPORTS))
    r = query.impact(g, "hub.py", direction="down", max_depth=1, cap=3)
    assert len(r["downstream"][1]) == 3
    assert r["downstream_truncated"] is True


def test_mentions_relation_included():
    """A decision node's upstream is the docs that mention it (MENTIONS edge)."""
    g = Graph(project="t")
    g.add_node(Node(id="README.md", type=NodeType.STRUCTURE, label="README.md", path="README.md"))
    g.add_node(Node(id="decision:D-X-1", type=NodeType.DECISION, label="D-X-1"))
    g.add_edge(Edge("README.md", "decision:D-X-1", EdgeType.MENTIONS))
    r = query.impact(g, "decision:D-X-1", direction="up", max_depth=1)
    assert {e["id"] for e in r["upstream"][1]} == {"README.md"}


def test_belongs_to_excluded_by_default():
    """Area membership must not count as a dependency (would link every file to its area)."""
    g = Graph(project="t")
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    g.add_node(Node(id="area:.", type=NodeType.AREA, label="."))
    g.add_edge(Edge("a.py", "area:.", EdgeType.BELONGS_TO))
    r = query.impact(g, "a.py", direction="down", max_depth=1)
    assert r["downstream"].get(1, []) == []


def test_bad_direction_raises():
    with pytest.raises(ValueError):
        query.impact(_g(), "a.py", direction="sideways")


def test_impact_is_deterministic():
    assert query.impact(_g(), "b.py") == query.impact(_g(), "b.py")
