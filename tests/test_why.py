"""Tests for `why` — shortest path between two nodes."""

from __future__ import annotations

from second_brain import query
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _g() -> Graph:
    g = Graph(project="t")
    for x in ("a", "b", "c", "d", "iso"):
        g.add_node(Node(id=x, type=NodeType.PROGRAM, label=x, path=x))
    g.add_edge(Edge("a", "b", EdgeType.IMPORTS))
    g.add_edge(Edge("b", "c", EdgeType.IMPORTS))
    g.add_edge(Edge("a", "d", EdgeType.IMPORTS))
    g.add_edge(Edge("d", "c", EdgeType.IMPORTS))  # two length-2 paths a-b-c and a-d-c
    return g


def test_shortest_path_deterministic_tie():
    r = query.why(_g(), "a", "c")
    assert r["exists"] and r["connected"] and r["length"] == 2
    assert [n["id"] for n in r["path"]] == ["a", "b", "c"]  # b < d -> a-b-c
    assert [e["type"] for e in r["edges"]] == ["imports", "imports"]


def test_undirected():
    r = query.why(_g(), "c", "a")  # reverse direction still connected (undirected)
    assert r["connected"] and r["length"] == 2


def test_same_node():
    r = query.why(_g(), "a", "a")
    assert r["length"] == 0 and [n["id"] for n in r["path"]] == ["a"] and r["edges"] == []


def test_unknown_node():
    assert query.why(_g(), "a", "nope")["exists"] is False
    assert query.why(_g(), "nope", "a")["exists"] is False


def test_disconnected():
    r = query.why(_g(), "a", "iso")
    assert r["exists"] is True and r["connected"] is False and r["path"] == []
