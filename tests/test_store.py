"""Store loaders degrade to None on corrupt / non-dict JSON (never crash a query)."""

from __future__ import annotations

from second_brain import store
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def test_load_graph_on_json_array_returns_none(tmp_path):
    d = tmp_path / ".secondbrain"
    d.mkdir()
    (d / "graph.json").write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not a dict
    assert store.load_graph(tmp_path) is None


def test_round_trip_with_symbol_nodes(tmp_path):
    g = Graph(project="p")
    g.add_node(Node(id="m.py", type=NodeType.PROGRAM, label="m.py", path="m.py"))
    g.add_node(Node(id="m.py::f", type=NodeType.SYMBOL, label="f", meta={"qualname": "f"}))
    g.add_edge(Edge("m.py", "m.py::f", EdgeType.DEFINES))
    store.save(tmp_path, g, {}, signature={"m.py": "1:2"}, symbols=True)
    back = store.load_graph(tmp_path)
    assert back is not None
    assert back.nodes["m.py::f"].type is NodeType.SYMBOL
    assert store.load_symbols_mode(tmp_path) is True
