"""Tests for deterministic community detection."""

from __future__ import annotations

from pathlib import Path

from second_brain import communities, operational
from second_brain.indexer import build_graph
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _file(g: Graph, nid: str) -> None:
    g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))


def _imp(g: Graph, a: str, b: str) -> None:
    g.add_edge(Edge(a, b, EdgeType.IMPORTS))


def test_detect_is_deterministic():
    g = build_graph(FIXTURE)
    assert communities.detect(g) == communities.detect(g)


def test_connected_chain_is_one_community():
    g = Graph(project="t")
    for nid in ("a.py", "b.py", "c.py"):
        _file(g, nid)
    _imp(g, "a.py", "b.py")
    _imp(g, "b.py", "c.py")
    comm = communities.detect(g)
    assert comm["a.py"] == comm["b.py"] == comm["c.py"]


def test_disconnected_components_are_distinct():
    g = Graph(project="t")
    for nid in ("a1.py", "a2.py", "b1.py", "b2.py"):
        _file(g, nid)
    _imp(g, "a1.py", "a2.py")
    _imp(g, "b1.py", "b2.py")
    comm = communities.detect(g)
    assert comm["a1.py"] == comm["a2.py"]
    assert comm["b1.py"] == comm["b2.py"]
    assert comm["a1.py"] != comm["b1.py"]


def test_isolated_file_falls_back_to_area():
    g = Graph(project="t")
    g.add_node(Node(id="src/lonely.py", type=NodeType.PROGRAM,
                    label="lonely.py", path="src/lonely.py"))
    comm = communities.detect(g)
    assert comm["src/lonely.py"] == "area:src"


def test_areas_and_decisions_excluded():
    g = build_graph(FIXTURE)
    operational.add_decisions(g, FIXTURE)
    comm = communities.detect(g)
    assert not any(k.startswith("area:") for k in comm)
    assert not any(k.startswith("decision:") for k in comm)


def test_summarize_orders_by_size_and_names():
    g = Graph(project="t")
    for nid in ("x1.py", "x2.py", "x3.py", "y1.py", "y2.py"):
        _file(g, nid)
    _imp(g, "x1.py", "x2.py")
    _imp(g, "x2.py", "x3.py")
    _imp(g, "y1.py", "y2.py")
    comm = {"x1.py": "X", "x2.py": "X", "x3.py": "X", "y1.py": "Y", "y2.py": "Y"}
    rows = communities.summarize(g, comm)
    assert rows[0]["name"] == "Cluster 1" and rows[0]["size"] == 3
    assert rows[1]["name"] == "Cluster 2" and rows[1]["size"] == 2
    assert "x1.py" in rows[0]["key_files"]


def test_summarize_cohesion_half():
    g = Graph(project="t")
    for nid in ("x1.py", "x2.py", "y1.py"):
        _file(g, nid)
    _imp(g, "x1.py", "x2.py")  # internal to X
    _imp(g, "x2.py", "y1.py")  # boundary X<->Y
    comm = {"x1.py": "X", "x2.py": "X", "y1.py": "Y"}
    rows = {r["label"]: r for r in communities.summarize(g, comm)}
    assert rows["X"]["cohesion"] == 0.5


def test_surprising_edges_finds_cross_links_only():
    g = Graph(project="t")
    for nid in ("x1.py", "x2.py", "y1.py"):
        _file(g, nid)
    _imp(g, "x1.py", "x2.py")
    _imp(g, "x2.py", "y1.py")  # cross-community
    comm = {"x1.py": "X", "x2.py": "X", "y1.py": "Y"}
    sur = communities.surprising_edges(g, comm)
    assert any(s["source"] == "x2.py" and s["target"] == "y1.py" for s in sur)
    assert not any(s["source"] == "x1.py" and s["target"] == "x2.py" for s in sur)


def test_names_are_size_ordered():
    comm = {"a": "BIG", "b": "BIG", "c": "BIG", "d": "small", "e": "small", "f": "solo"}
    name_of = communities.names(comm)
    assert name_of["BIG"] == "Cluster 1"
    assert name_of["small"] == "Cluster 2"
    assert name_of["solo"] == "Cluster 3"


def test_detect_runs_on_fixture():
    g = build_graph(FIXTURE)
    comm = communities.detect(g)
    assert comm
    assert all(isinstance(v, str) for v in comm.values())
