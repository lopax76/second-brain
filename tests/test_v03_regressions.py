"""Regression tests added after the v0.3 cross-check.

Each test pins a specific issue raised by the review agents: community determinism across
insertion order, decision exclusion by type, impact depth-0 / cap / cycle behaviour, and the
agent-integration anti-clobber guards.
"""

from __future__ import annotations

from second_brain import agent_integration as ai
from second_brain import communities, query
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _file(g: Graph, nid: str) -> None:
    g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))


def _imp(g: Graph, a: str, b: str) -> None:
    g.add_edge(Edge(a, b, EdgeType.IMPORTS))


# --- communities: determinism is independent of node/edge insertion order ---
def test_communities_insertion_order_independent():
    def make(node_order, edge_order):
        g = Graph(project="t")
        for nid in node_order:
            _file(g, nid)
        for a, b in edge_order:
            _imp(g, a, b)
        return g

    g1 = make(["a.py", "b.py", "c.py"], [("a.py", "b.py"), ("b.py", "c.py")])
    g2 = make(["c.py", "a.py", "b.py"], [("b.py", "c.py"), ("a.py", "b.py")])
    assert communities.detect(g1) == communities.detect(g2)


def test_communities_excludes_decision_even_with_path():
    g = Graph(project="t")
    g.add_node(Node(id="d", type=NodeType.DECISION, label="D-X-1", path="d.md"))
    _file(g, "a.py")
    comm = communities.detect(g)
    assert "d" not in comm
    assert "a.py" in comm


# --- impact: max_depth=0, cap-no-reappear, cycles ---
def test_impact_depth_zero_is_empty():
    g = Graph(project="t")
    _file(g, "a.py")
    _file(g, "b.py")
    _imp(g, "a.py", "b.py")
    r = query.impact(g, "a.py", direction="down", max_depth=0)
    assert r["downstream"] == {}


def test_impact_capped_node_does_not_reappear_deeper():
    g = Graph(project="t")
    g.add_node(Node(id="hub.py", type=NodeType.PROGRAM, label="hub.py", path="hub.py"))
    for nid in ("d0.py", "d1.py", "d2.py", "d3.py"):
        _file(g, nid)
        _imp(g, "hub.py", nid)
    _imp(g, "d0.py", "d3.py")  # d3 also reachable at depth 2 via a kept node
    r = query.impact(g, "hub.py", direction="down", max_depth=2, cap=2)
    kept = {e["id"] for e in r["downstream"].get(1, [])}
    deeper = {e["id"] for e in r["downstream"].get(2, [])}
    assert len(kept) == 2 and r["downstream_truncated"] is True
    assert "d3.py" not in deeper  # dropped by the cap at depth 1 -> never resurfaces


def test_impact_handles_cycle():
    g = Graph(project="t")
    for nid in ("a.py", "b.py", "c.py"):
        _file(g, nid)
    _imp(g, "a.py", "b.py")
    _imp(g, "b.py", "c.py")
    _imp(g, "c.py", "a.py")
    r = query.impact(g, "a.py", direction="down", max_depth=5)  # must terminate
    seen = {e["id"] for layer in r["downstream"].values() for e in layer}
    assert seen == {"b.py", "c.py"}  # start node not re-listed; no infinite loop


# --- agent integration: never clobber on inverted markers / non-object settings ---
def test_remove_context_files_ignores_inverted_markers(tmp_path):
    content = f"top\n{ai._END}\nmiddle\n{ai._START}\nbottom\n"
    (tmp_path / "CLAUDE.md").write_text(content, encoding="utf-8")
    res = ai.remove_context_files(tmp_path)
    assert res["CLAUDE.md"] == "absent"
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == content


def test_install_claude_hook_refuses_non_object_settings(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, but not an object
    res = ai.install_claude_hook(tmp_path)
    assert res.startswith("error")
    assert p.read_text(encoding="utf-8") == "[1, 2, 3]"  # left unchanged


def test_install_claude_hook_refuses_corrupt_settings(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ not json", encoding="utf-8")
    res = ai.install_claude_hook(tmp_path)
    assert res.startswith("error")
    assert p.read_text(encoding="utf-8") == "{ not json"  # left unchanged
