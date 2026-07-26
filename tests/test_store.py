"""Store loaders degrade to None on corrupt / non-dict JSON (never crash a query)."""

from __future__ import annotations

import os

import pytest

from second_brain import store
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _one_node_graph(node_id: str) -> Graph:
    g = Graph(project="p")
    g.add_node(Node(id=node_id, type=NodeType.PROGRAM, label=node_id, path=node_id))
    return g


def test_a_failed_write_leaves_the_previous_store_intact(tmp_path, monkeypatch):
    """The atomicity the module docstring promises, made observable without a real crash.

    ``_atomic_write`` writes to a temp file and then ``os.replace``s it into place, so an
    interrupted write cannot leave a half-written graph. Nothing verified that: replacing the body
    with a direct ``open()``/``write()`` on the destination kept the whole suite green.
    """
    store.save(tmp_path, _one_node_graph("first.py"), {}, signature={}, symbols=False)
    assert store.load_graph(tmp_path) is not None

    def boom(*_a, **_k):
        raise OSError("interrupted")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save(tmp_path, _one_node_graph("second.py"), {}, signature={}, symbols=False)
    monkeypatch.undo()

    survived = store.load_graph(tmp_path)
    assert survived is not None, "the destination was clobbered by a write that failed"
    assert "first.py" in survived.nodes and "second.py" not in survived.nodes
    leftovers = list((tmp_path / ".secondbrain").glob(".tmp-*"))
    assert leftovers == [], f"temporary files left behind: {leftovers}"


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
