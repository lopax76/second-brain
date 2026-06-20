"""v0.8: centralized budget helper, signatures in focus, ranked+budgeted impact, view --focus,
graph schema_version (concepts absorbed from aider's repomap + galimar/veridge, all zero-dep)."""

from __future__ import annotations

from second_brain import budget, query
from second_brain.cli import main
from second_brain.indexer import build_graph
from second_brain.model import SCHEMA_VERSION, Edge, EdgeType, Graph, Node, NodeType


def _prog(g: Graph, nid: str) -> None:
    g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))


# --------------------------- budget.py ---------------------------------------
def test_budget_costs():
    n = Node(id="a/b.py", type=NodeType.PROGRAM, label="b.py", path="a/b.py")
    assert budget.node_cost(n) >= 1
    assert budget.text_cost("") == 1
    assert budget.text_cost("x" * 40) > budget.text_cost("x")


def test_budget_fit_keeps_first_and_truncates():
    kept, spent, trunc = budget.fit(["aaaa", "bbbb", "cccc"], lambda s: 10, budget=15)
    assert kept == ["aaaa"] and trunc and spent == 10
    keep_all, _, trunc2 = budget.fit(["a", "b"], lambda s: 99, budget=0)
    assert keep_all == ["a", "b"] and not trunc2          # budget <= 0 keeps all
    big, _, _ = budget.fit(["huge"], lambda s: 999, budget=1)
    assert big == ["huge"]                                # first always admitted


# --------------------------- signatures in focus -----------------------------
def test_attach_signatures_enriches_python_only(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "m.py").write_text(
        "def greet(name: str) -> str:\n    return name\n\n"
        "class A:\n    def run(self):\n        pass\n",
        encoding="utf-8")
    (proj / "d.md").write_text("# doc mentioning greet\n", encoding="utf-8")
    g = build_graph(proj)
    res = query.attach_signatures(g, str(proj), query.focus(g, "greet run", budget_tokens=2000))
    assert "m.py" in res["signatures"]
    assert any("def greet" in r["signature"] for r in res["signatures"]["m.py"])
    assert "d.md" not in res["signatures"]                # non-Python skipped


def test_attach_signatures_respects_budget(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "big.py").write_text("\n".join(f"def f{i}(): pass" for i in range(50)) + "\n",
                                 encoding="utf-8")
    g = build_graph(proj)
    res = query.attach_signatures(g, str(proj), query.focus(g, "f0", budget_tokens=2000),
                                  budget_tokens=1)
    assert sum(len(v) for v in res["signatures"].values()) == 1   # tiny budget -> only the first


# --------------------------- impact ranked + budgeted ------------------------
def test_impact_adds_degree_default_unchanged():
    g = Graph(project="t")
    _prog(g, "hub.py")
    for i in range(5):
        _prog(g, f"u{i}.py")
        g.add_edge(Edge(f"u{i}.py", "hub.py", EdgeType.IMPORTS))
    entries = query.impact(g, "hub.py", direction="up")["upstream"][1]
    assert len(entries) == 5 and all("degree" in e for e in entries)


def test_impact_budget_ranks_most_connected_first_and_trims():
    g = Graph(project="t")
    _prog(g, "hub.py")
    for i in range(6):
        _prog(g, f"u{i}.py")
        g.add_edge(Edge(f"u{i}.py", "hub.py", EdgeType.IMPORTS))
    for i in range(4):                                   # u0 becomes a hub itself (high degree)
        _prog(g, f"x{i}.py")
        g.add_edge(Edge("u0.py", f"x{i}.py", EdgeType.IMPORTS))
    res = query.impact(g, "hub.py", direction="up", budget_tokens=20)
    flat = [e["id"] for d in res["upstream"] for e in res["upstream"][d]]
    assert "u0.py" in flat and res["upstream_truncated"]
    assert len(flat) < 6                                 # trimmed to budget


# --------------------------- view --focus ------------------------------------
def test_view_focus_cli_writes_the_slice(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "b.py").write_text("import a\n", encoding="utf-8")
    assert main(["build", str(proj)]) == 0
    assert main(["view", str(proj), "--focus", "a"]) == 0
    assert (proj / ".secondbrain" / "view.html").is_file()


# --------------------------- schema_version ----------------------------------
def test_schema_version_present_and_tolerated():
    g = Graph(project="t")
    _prog(g, "a.py")
    d = g.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION == 1
    assert "a.py" in Graph.from_dict(d).nodes            # round-trips, field tolerated


# --------------------------- MCP in-process graph cache (v0.8.1) -------------
def test_mcp_graph_cache_reuses_within_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "150")
    from second_brain import mcp_server
    mcp_server.clear_graph_cache()
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    g1 = mcp_server._graph(str(proj))
    g2 = mcp_server._graph(str(proj))
    assert g1 is g2                                   # within TTL window: same object, zero I/O
    mcp_server.clear_graph_cache()
    assert mcp_server._graph(str(proj)) is not g1     # after clear: fresh load


def test_mcp_graph_cache_off_when_ttl_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    from second_brain import mcp_server
    mcp_server.clear_graph_cache()
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert mcp_server._graph(str(proj)) is not mcp_server._graph(str(proj))  # caching disabled


def test_refresh_ttl_default_is_150(monkeypatch):
    import second_brain.freshness as fr
    monkeypatch.delenv("SECOND_BRAIN_REFRESH_TTL", raising=False)
    assert fr._refresh_ttl() == 150.0
