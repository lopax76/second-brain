"""Tests for the GRAPH_REPORT.md one-pager."""

from __future__ import annotations

import shutil
from pathlib import Path

from second_brain import operational, report
from second_brain.indexer import build_graph
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _graph() -> Graph:
    g = build_graph(FIXTURE)
    operational.add_decisions(g, FIXTURE)
    return g


def test_report_has_key_sections():
    md = report.render_report(_graph(), root=str(FIXTURE))
    for h in (
        "# Second Brain", "## Scale", "## God nodes", "## Communities",
        "## Surprising connections", "## Decisions", "## Suggested questions", "## Problems",
    ):
        assert h in md


def test_report_is_deterministic():
    g = _graph()
    assert report.render_report(g, root=str(FIXTURE)) == report.render_report(g, root=str(FIXTURE))


def test_decision_families_counted():
    g = Graph(project="t")
    g.add_node(Node(id="doc.md", type=NodeType.STRUCTURE, label="doc.md", path="doc.md"))
    for did in ("D-X-1", "D-X-2", "ADR-7"):
        g.add_node(Node(id=f"decision:{did}", type=NodeType.DECISION, label=did))
        g.add_edge(Edge("doc.md", f"decision:{did}", EdgeType.MENTIONS))
    md = report.render_report(g)
    assert "D-X: 2" in md
    assert "ADR: 1" in md


def test_report_flags_broken_reference():
    # the fixture contains a known broken reference (missing.md)
    md = report.render_report(_graph(), root=str(FIXTURE))
    assert "broken references" in md


def test_write_report_creates_file(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    out = report.write_report(proj, build_graph(proj))
    assert out.is_file() and out.name == "GRAPH_REPORT.md"
    assert "## Communities" in out.read_text(encoding="utf-8")


def test_clean_project_reports_no_problems(tmp_path):
    proj = tmp_path / "clean"
    proj.mkdir()
    (proj / "README.md").write_text("# clean\nno links\n", encoding="utf-8")
    (proj / "app.py").write_text("x = 1\n", encoding="utf-8")
    md = report.render_report(build_graph(proj), root=str(proj))
    assert "## Problems" in md
