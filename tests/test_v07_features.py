"""v0.7: BM25 lexical seeding for focus + transparent budgeting (limit) on flood-prone tools."""

from __future__ import annotations

from second_brain import bm25, query
from second_brain.cli import main
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _prog(g: Graph, nid: str) -> None:
    g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))


# --------------------------- BM25 unit ---------------------------------------
def test_bm25_tokenize_splits_snake_case():
    assert bm25.tokenize("src/auth_login.py") == ["src", "auth", "login", "py"]
    assert "a" not in bm25.tokenize("a bb ccc")          # 1-char tokens dropped


def test_bm25_rare_term_outranks_common():
    m = bm25.BM25({"d1": "report report report", "d2": "report pagerank"})
    # 'pagerank' appears in one doc (high IDF); it lifts d2 above d1 despite d1's term frequency
    assert m.score("report pagerank", "d2") > m.score("report pagerank", "d1")


def test_bm25_absent_term_is_zero():
    m = bm25.BM25({"d1": "alpha beta"})
    assert m.score("gamma", "d1") == 0.0
    assert m.scores("gamma") == {}


def test_bm25_is_deterministic():
    docs = {"a": "foo bar", "b": "bar baz qux"}
    assert bm25.BM25(docs).scores("bar baz") == bm25.BM25(docs).scores("bar baz")


# --------------------------- focus: BM25 seeding -----------------------------
def test_focus_bm25_anchors_on_the_discriminating_file():
    query.clear_focus_cache()
    g = Graph(project="t")
    for i in range(5):
        _prog(g, f"r{i}/report.py")                       # five generic 'report' files
    _prog(g, "core/pagerank_report.py")                   # also carries the rare 'pagerank'
    seeds = query._focus_seeds(g, "pagerank report")
    assert seeds["core/pagerank_report.py"] == max(seeds.values())
    res = query.focus(g, "pagerank report", budget_tokens=300)
    assert not res["fallback"]
    assert res["nodes"][0]["id"] == "core/pagerank_report.py"


def test_focus_searches_symbol_qualname():
    query.clear_focus_cache()
    g = Graph(project="t")
    _prog(g, "m.py")
    g.add_node(Node(id="m.py::Auth.login", type=NodeType.SYMBOL, label="login",
                    meta={"qualname": "Auth.login", "file": "m.py"}))
    assert "m.py::Auth.login" in query._focus_seeds(g, "login")


def test_focus_still_falls_back_with_no_match():
    query.clear_focus_cache()
    g = Graph(project="t")
    _prog(g, "a.py")
    res = query.focus(g, "zzzznothing")
    assert res["fallback"] is True and res["seeds"] == []


# --------------------------- neighbors limit ---------------------------------
def test_neighbors_limit_caps_and_reports_total():
    g = Graph(project="t")
    _prog(g, "hub.py")
    for i in range(6):
        _prog(g, f"u{i}.py")
        g.add_edge(Edge(f"u{i}.py", "hub.py", EdgeType.IMPORTS))
    full = query.neighbors(g, "hub.py")
    assert full["incoming_total"] == 6 and len(full["incoming"]) == 6 and not full["truncated"]
    capped = query.neighbors(g, "hub.py", limit=2)
    assert capped["incoming_total"] == 6 and len(capped["incoming"]) == 2 and capped["truncated"]


# --------------------------- communities limit -------------------------------
def test_community_summary_limit():
    g = Graph(project="t")
    for a, b in [("x1.py", "x2.py"), ("y1.py", "y2.py"), ("z1.py", "z2.py")]:
        _prog(g, a)
        _prog(g, b)
        g.add_edge(Edge(a, b, EdgeType.IMPORTS))
    full = query.community_summary(g)
    assert full["count"] == 3 and full["shown"] == 3 and not full["truncated"]
    capped = query.community_summary(g, limit=2)
    assert capped["count"] == 3 and capped["shown"] == 2 and capped["truncated"]
    assert len(capped["communities"]) == 2


# --------------------------- CLI smoke for the new flags ---------------------
def test_cli_limit_flags(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "b.py").write_text("import a\n", encoding="utf-8")
    assert main(["build", str(proj)]) == 0
    assert main(["neighbors", "a.py", str(proj), "--limit", "1"]) == 0
    assert main(["communities", str(proj), "--limit", "1"]) == 0
