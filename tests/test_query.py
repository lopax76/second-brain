"""Tests for the low-token query layer."""

from __future__ import annotations

from pathlib import Path

from second_brain import query
from second_brain.indexer import build_graph
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def test_project_map():
    m = query.project_map(build_graph(FIXTURE))
    assert m["project"] == "sample_project"
    assert m["files"] == 8
    assert any(a["area"] == "src" for a in m["by_area"])
    assert m["node_types"].get("program") == 3
    ids = {x["id"] for x in m["most_connected"]}
    assert "src/app.py" in ids


def test_find():
    g = build_graph(FIXTURE)
    res = query.find(g, "util")
    assert any(r["id"] == "src/util.py" for r in res)
    assert query.find(g, "") == []


def test_neighbors():
    g = build_graph(FIXTURE)
    n = query.neighbors(g, "src/app.py")
    assert n is not None and n["type"] == "program"
    assert "src/util.py" in {o["id"] for o in n["outgoing"]}
    assert query.neighbors(g, "does/not/exist") is None


def test_subgraph_one_hop():
    sg = query.subgraph(build_graph(FIXTURE), "src/app.py", hops=1)
    ids = {n["id"] for n in sg["nodes"]}
    assert "src/app.py" in ids and "src/util.py" in ids


def test_subgraph_ignores_dangling_edge():
    """An edge pointing at an id with no node must not crash subgraph traversal."""
    g = Graph(project="t")
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    g.add_edge(Edge("a.py", "ghost.py", EdgeType.IMPORTS))  # ghost.py has no node
    sg = query.subgraph(g, "a.py", hops=2)
    assert {n["id"] for n in sg["nodes"]} == {"a.py"}


def test_backbone_keeps_connected_and_summarizes_isolated():
    g = build_graph(FIXTURE)
    bb = query.backbone(g)
    assert len(bb.nodes) < len(g.nodes)                       # isolated files dropped
    assert any(n.type is NodeType.AREA for n in bb.nodes.values())
    assert "src/app.py" in bb.nodes and "src/util.py" in bb.nodes  # connected code kept
    hidden = sum(n.meta.get("hidden", 0) for n in bb.nodes.values())
    assert hidden >= 1                                         # e.g. data/store.csv summarized


def test_find_is_deterministic_and_id_sorted():
    """find() returns the same id-sorted result regardless of node insertion order."""
    ids = [f"src/m{i}_util.py" for i in (5, 1, 9, 3, 7)]
    g = Graph(project="t")
    for nid in ids:
        g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))
    got = [r["id"] for r in query.find(g, "util", limit=3)]
    assert got == sorted(ids)[:3]
