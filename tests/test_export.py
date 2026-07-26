"""Tests for GraphML export and the report's git-churn section."""

from __future__ import annotations

from xml.dom import minidom

from second_brain import report
from second_brain.cli import main
from second_brain.export import to_graphml
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _g() -> Graph:
    g = Graph(project="proj & <x>")  # special chars must be escaped
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    g.add_node(Node(id="b.py", type=NodeType.PROGRAM, label="b & b", path="b.py"))
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))
    return g


def test_graphml_is_well_formed_xml():
    xml = to_graphml(_g())
    # minidom raises on malformed XML — proves escaping is correct.
    dom = minidom.parseString(xml)
    assert dom.getElementsByTagName("node").length == 2
    assert dom.getElementsByTagName("edge").length == 1


def test_graphml_deterministic():
    """Two equivalent graphs built in OPPOSITE insertion order must export identically.

    ``assert to_graphml(g) == to_graphml(g)`` was true of any pure function of its argument, so it
    could not notice a dependency on insertion order — which is exactly what the module promises
    to be free of ("nodes/edges sorted like graph.json, for clean diffs").
    """
    nodes = [
        Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"),
        Node(id="b.py", type=NodeType.PROGRAM, label="b & b", path="b.py"),
        Node(id="c.py", type=NodeType.PROGRAM, label="c.py", path="c.py"),
    ]
    edges = [
        Edge("a.py", "b.py", EdgeType.IMPORTS),
        Edge("b.py", "c.py", EdgeType.IMPORTS),
        Edge("a.py", "c.py", EdgeType.IMPORTS),
    ]

    ascending = Graph(project="proj & <x>")
    for n in nodes:
        ascending.add_node(n)
    for e in edges:
        ascending.add_edge(e)

    descending = Graph(project="proj & <x>")
    for n in reversed(nodes):
        descending.add_node(n)
    for e in reversed(edges):
        descending.add_edge(e)

    assert to_graphml(ascending) == to_graphml(descending)


def test_export_cli_writes_file(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "app.py").write_text("import os\n", encoding="utf-8")
    out = tmp_path / "graph.graphml"
    assert main(["export", str(proj), "--out", str(out)]) == 0
    assert out.is_file()
    minidom.parseString(out.read_text(encoding="utf-8"))  # valid XML


def test_report_churn_section():
    g = Graph(project="t")
    g.add_node(Node(id="hot.py", type=NodeType.PROGRAM, label="hot.py", path="hot.py"))
    g.add_node(Node(id="cold.py", type=NodeType.PROGRAM, label="cold.py", path="cold.py"))
    for h in ("c1", "c2", "c3"):
        g.add_node(Node(id=f"session:{h}", type=NodeType.SESSION, label=h))
        g.add_edge(Edge(f"session:{h}", "hot.py", EdgeType.TOUCHES))
    g.add_node(Node(id="session:c4", type=NodeType.SESSION, label="c4"))
    g.add_edge(Edge("session:c4", "cold.py", EdgeType.TOUCHES))
    md = report.render_report(g, scan_problems=False)
    assert "Most-changed files" in md
    churn_section = md[md.index("Most-changed files"):]
    assert "`hot.py` — 3 commits" in churn_section
    # within the churn section, hot.py (3 commits) ranks above cold.py (1)
    assert churn_section.index("hot.py") < churn_section.index("cold.py")


def test_report_no_churn_section_without_git():
    g = Graph(project="t")
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    md = report.render_report(g, scan_problems=False)
    assert "Most-changed files" not in md
