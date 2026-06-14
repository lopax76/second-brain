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


def test_render_view_is_single_self_contained_file() -> None:
    html = render_view(_tiny_graph())
    assert "__SB_DATA__" not in html  # placeholder token was replaced
    assert '"demo"' in html  # the project name is present in the inlined payload
    # the graph library is INLINED — not referenced as a sibling/external file or a remote URL,
    # so the single HTML renders even when moved or shared on its own.
    assert "<script src=" not in html
    assert "vis.Network" in html  # the rendering library is used in the page
    assert "vis-network" in html  # the embedded library / attribution is present
    assert "cdnjs" not in html and "unpkg" not in html


def test_template_is_offline_and_references_the_vendored_bundle() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    # the viewer is fully offline; stale "fetches from a CDN" copy must not creep back in
    assert "from a CDN" not in text
    assert "cdnjs" not in text and "unpkg" not in text
    # it loads the vendored bundle (inlined at render time), not a remote URL
    assert "vis-bundle.min.js" in text


def test_write_view_is_self_contained_single_file(tmp_path) -> None:
    write_view(tmp_path, _tiny_graph())
    d = tmp_path / ".secondbrain"
    assert (d / "view.html").is_file()
    # no sibling library file is needed: everything is inlined in the one HTML
    assert not (d / "vis-bundle.min.js").exists()
    html = (d / "view.html").read_text(encoding="utf-8")
    assert "__SB_DATA__" not in html
    assert "vis.Network" in html and "<script src=" not in html


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
