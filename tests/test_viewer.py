"""Tests for the 3D viewer renderer and its offline/template guarantees."""

from __future__ import annotations

from second_brain.model import Edge, EdgeType, Graph, Node, NodeType
from second_brain.viewer import _TEMPLATE, render_view, write_view


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


def test_write_view_emits_offline_assets(tmp_path) -> None:
    write_view(tmp_path, _tiny_graph())
    d = tmp_path / ".secondbrain"
    assert (d / "view.html").is_file()
    # the vendored 3D library is copied next to the page -> the viewer works offline
    assert (d / "3d-force-graph.min.js").is_file()
    assert "__SB_DATA__" not in (d / "view.html").read_text(encoding="utf-8")


def test_render_view_escapes_script_breakout() -> None:
    g = Graph(project="x")
    g.add_node(
        Node(
            id="a.py",
            type=NodeType.PROGRAM,
            label="a</script><script>alert(1)</script>",
            path="a.py",
        )
    )
    html = render_view(g)
    # every "<" in the data is escaped (<), so a hostile label cannot break out of the block
    assert "</script><script>" not in html
