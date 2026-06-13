"""Tests for the 3D viewer renderer and its offline/template guarantees."""

from __future__ import annotations

from secondbrain.model import Edge, EdgeType, Graph, Node, NodeType
from secondbrain.viewer import _TEMPLATE, render_view


def _tiny_graph() -> Graph:
    g = Graph(project="demo")
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    g.add_node(Node(id="b.py", type=NodeType.PROGRAM, label="b.py", path="b.py"))
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))
    return g


def test_render_view_inlines_data_and_local_library() -> None:
    html = render_view(_tiny_graph())
    assert "__SB_DATA__" not in html  # placeholder token was replaced
    assert '"demo"' in html  # the project name is present in the inlined payload
    # the 3D library is referenced locally (vendored next to the page), never from a remote URL
    assert '<script src="3d-force-graph.min.js">' in html
    assert "cdnjs" not in html and "unpkg" not in html and "https://" not in html


def test_template_does_not_claim_a_cdn_dependency() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    # the viewer is fully offline; stale "fetches from a CDN" copy must not creep back in
    assert "from a CDN" not in text
    # render stays robust when the page is opened in a background tab/window
    assert "visibilitychange" in text
