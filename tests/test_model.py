"""Tests for the graph model: typing, colors, dedup, queries, serialization roundtrip."""

from __future__ import annotations

from second_brain.model import (
    EDGE_COLORS,
    NODE_COLORS,
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
)


def test_every_node_and_edge_type_has_a_color():
    # Guards against adding a type without a color (the 3D view would break).
    for nt in NodeType:
        assert nt in NODE_COLORS and NODE_COLORS[nt].startswith("#")
    for et in EdgeType:
        assert et in EDGE_COLORS and EDGE_COLORS[et].startswith("#")


def test_node_to_dict_does_not_persist_color():
    # Color is derived from type (single source of truth), not stored per node.
    n = Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py")
    d = n.to_dict()
    assert d["type"] == "program"
    assert "color" not in d
    assert d["path"] == "a.py"
    # The color is still resolvable from the canonical map.
    assert NODE_COLORS[NodeType.PROGRAM].startswith("#")


def test_to_dict_is_deterministically_ordered():
    g = Graph(project="d")
    for nid in ("z", "a", "m"):
        g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid))
    g.add_edge(Edge("z", "a", EdgeType.IMPORTS))
    g.add_edge(Edge("a", "m", EdgeType.IMPORTS))
    d = g.to_dict()
    assert [n["id"] for n in d["nodes"]] == ["a", "m", "z"]
    assert [(e["source"], e["target"]) for e in d["edges"]] == [("a", "m"), ("z", "a")]


def test_add_node_first_wins():
    g = Graph()
    first = g.add_node(Node(id="x", type=NodeType.PROGRAM, label="x"))
    again = g.add_node(Node(id="x", type=NodeType.REPORT, label="x2"))
    assert again is first  # existing kept
    assert g.get_node("x").type is NodeType.PROGRAM
    assert len(g.nodes) == 1


def test_add_edge_dedup_by_source_target_type():
    g = Graph()
    e1 = Edge("a", "b", EdgeType.IMPORTS)
    e2 = Edge("a", "b", EdgeType.IMPORTS)  # duplicate
    e3 = Edge("a", "b", EdgeType.REFERENCES)  # different type -> kept
    assert g.add_edge(e1) is True
    assert g.add_edge(e2) is False
    assert g.add_edge(e3) is True
    assert len(g.edges) == 2


def test_neighbors_direction():
    g = Graph()
    for nid in ("a", "b", "c"):
        g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid))
    g.add_edge(Edge("a", "b", EdgeType.IMPORTS))
    g.add_edge(Edge("c", "a", EdgeType.IMPORTS))
    assert g.neighbors("a", "out") == ["b"]
    assert g.neighbors("a", "in") == ["c"]
    assert g.neighbors("a", "both") == ["b", "c"]
    assert g.degree("a") == 2


def test_counts():
    g = Graph()
    g.add_node(Node(id="a", type=NodeType.PROGRAM, label="a"))
    g.add_node(Node(id="b", type=NodeType.PROGRAM, label="b"))
    g.add_node(Node(id="r", type=NodeType.REPORT, label="r"))
    g.add_edge(Edge("a", "b", EdgeType.IMPORTS))
    c = g.counts()
    assert c["nodes"]["program"] == 2
    assert c["nodes"]["report"] == 1
    assert c["edges"]["imports"] == 1


def test_serialization_roundtrip():
    g = Graph(project="demo")
    g.add_node(Node(id="a", type=NodeType.PROGRAM, label="a", description="hi", path="a"))
    g.add_node(Node(id="area:src", type=NodeType.AREA, label="src"))
    g.add_edge(Edge("a", "area:src", EdgeType.BELONGS_TO))
    back = Graph.from_dict(g.to_dict())
    assert back.project == "demo"
    assert back.get_node("a").description == "hi"
    assert len(back.nodes) == 2
    assert len(back.edges) == 1
    # JSON is valid and stable
    assert '"project": "demo"' in g.to_json()
