"""The opt-in symbol layer is off by default and adds symbol nodes + edges when requested."""

from __future__ import annotations

from second_brain.indexer import build_graph
from second_brain.model import EdgeType, NodeType


def _project(tmp_path):
    (tmp_path / "m.py").write_text(
        "def helper():\n    return 1\n\n\n"
        "class A:\n    def run(self):\n        helper()\n        self.run()\n",
        encoding="utf-8",
    )
    return tmp_path


def test_symbols_off_by_default(tmp_path):
    g = build_graph(_project(tmp_path))
    assert not any(n.type is NodeType.SYMBOL for n in g.nodes.values())


def test_symbols_on_adds_nodes_and_edges(tmp_path):
    g = build_graph(_project(tmp_path), symbols=True)
    syms = {n.meta.get("qualname") for n in g.nodes.values() if n.type is NodeType.SYMBOL}
    assert {"helper", "A", "A.run"} <= syms
    defines = [e for e in g.edges if e.type is EdgeType.DEFINES]
    calls = {(e.source, e.target) for e in g.edges if e.type is EdgeType.CALLS}
    assert any(e.source == "m.py" for e in defines)
    assert ("m.py::A.run", "m.py::helper") in calls
    assert ("m.py::A.run", "m.py::A.run") in calls  # self.run() recursion


def test_symbol_nodes_have_no_path(tmp_path):
    # symbol nodes are sub-file entities -> no path, so file counts/orphans stay correct
    g = build_graph(_project(tmp_path), symbols=True)
    assert all(n.path is None for n in g.nodes.values() if n.type is NodeType.SYMBOL)
