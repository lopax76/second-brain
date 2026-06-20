"""v0.9.0: recency-weighted recall (ACT-R base-level) and opt-in .gitignore support."""

from __future__ import annotations

import json

from second_brain import recency
from second_brain.config import load_config
from second_brain.ignore import (
    gitignored,
    load_gitignore_rules,
)
from second_brain.indexer import build_graph, iter_files
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType
from second_brain.query import focus

RECENT = "2026-06-20T12:00:00+00:00"
OLD = "2026-01-01T12:00:00+00:00"  # ~170 days before RECENT


def _g_with_sessions() -> Graph:
    g = Graph(project="t")
    for f in ("a.py", "b.py"):
        g.add_node(Node(id=f, type=NodeType.PROGRAM, label=f, path=f))
    g.add_node(Node(id="session:new", type=NodeType.SESSION, label="new", meta={"date": RECENT}))
    g.add_node(Node(id="session:old", type=NodeType.SESSION, label="old", meta={"date": OLD}))
    g.add_edge(Edge("session:new", "b.py", EdgeType.TOUCHES))  # b touched recently
    g.add_edge(Edge("session:old", "a.py", EdgeType.TOUCHES))  # a touched long ago
    return g


# -- recency.recency_scores -------------------------------------------------------------------

def test_recency_empty_without_sessions():
    g = Graph(project="t")
    g.add_node(Node(id="a.py", type=NodeType.PROGRAM, label="a.py", path="a.py"))
    assert recency.recency_scores(g) == {}


def test_recency_recent_outranks_old():
    g = _g_with_sessions()
    s = recency.recency_scores(g, half_life_days=30.0)
    assert s["b.py"] == 1.0           # most recent -> normalised top
    assert s["b.py"] > s["a.py"]      # recency genuinely orders them (not a normalisation artifact)
    # OLD is exactly 170 days before RECENT; with b.py as the anchor (raw 1.0), a.py's normalised
    # score equals its decay. This PINS the anchor to the newest commit (a wall-clock anchor would
    # change a.py's age and break this exact equality).
    assert abs(s["a.py"] - 0.5 ** (170 / 30.0)) < 1e-9


def test_recency_frequency_accumulates():
    # Two files both touched recently; the one touched by MORE commits scores higher (frequency).
    g = Graph(project="t")
    for f in ("x.py", "y.py"):
        g.add_node(Node(id=f, type=NodeType.PROGRAM, label=f, path=f))
    for i, tgt in enumerate(("x.py", "x.py", "y.py")):
        sid = f"session:{i}"
        g.add_node(Node(id=sid, type=NodeType.SESSION, label=sid, meta={"date": RECENT}))
        g.add_edge(Edge(sid, tgt, EdgeType.TOUCHES))
    s = recency.recency_scores(g)
    assert s["x.py"] == 1.0           # 2 recent touches
    assert s["y.py"] == 0.5           # 1 recent touch -> half of x after normalisation


def test_recency_anchor_is_newest_commit_not_wall_clock():
    # Recency is anchored to the NEWEST commit IN THE GRAPH, not the wall clock. Adding a session
    # newer than RECENT moves the anchor forward, so b.py (was the newest -> 1.0) must now decay
    # below the new top. A wall-clock anchor could not produce this graph-relative shift.
    g = _g_with_sessions()
    s1 = recency.recency_scores(g)
    assert s1 == recency.recency_scores(g)  # stable across calls
    assert s1["b.py"] == 1.0                # b.py is the newest here
    future = "2026-09-01T12:00:00+00:00"
    g.add_node(Node(id="c.py", type=NodeType.PROGRAM, label="c.py", path="c.py"))
    g.add_node(Node(id="session:fut", type=NodeType.SESSION, label="fut", meta={"date": future}))
    g.add_edge(Edge("session:fut", "c.py", EdgeType.TOUCHES))
    s2 = recency.recency_scores(g)
    assert s2["c.py"] == 1.0     # the new newest commit becomes the anchor
    assert s2["b.py"] < 1.0      # b.py is now older than the anchor -> decays


def test_recency_mixed_naive_and_aware_dates_do_not_crash():
    # A non-%aI (timezone-naive) date must be coerced, not crash max()/subtraction when mixed
    # with offset-aware git dates.
    g = Graph(project="t")
    for f in ("a.py", "b.py"):
        g.add_node(Node(id=f, type=NodeType.PROGRAM, label=f, path=f))
    g.add_node(Node(id="session:aware", type=NodeType.SESSION, label="a", meta={"date": RECENT}))
    g.add_node(Node(id="session:naive", type=NodeType.SESSION, label="n",
                    meta={"date": "2026-01-01"}))  # naive, no offset
    g.add_edge(Edge("session:aware", "a.py", EdgeType.TOUCHES))
    g.add_edge(Edge("session:naive", "b.py", EdgeType.TOUCHES))
    s = recency.recency_scores(g)  # must not raise
    assert s["a.py"] == 1.0 and 0.0 < s["b.py"] < 1.0


# -- recency.blend ----------------------------------------------------------------------------

def test_blend_weight_zero_is_identity():
    base = {"a": 0.7, "b": 0.3}
    assert recency.blend(base, {"a": 0.0, "b": 1.0}, 0.0) == base


def test_blend_full_weight_is_recency():
    base = {"a": 0.9, "b": 0.1}
    out = recency.blend(base, {"b": 1.0}, 1.0)  # 'a' absent from recency -> 0
    assert out["b"] == 1.0
    assert out["a"] == 0.0


# -- focus integration ------------------------------------------------------------------------

def _g_important_vs_recent() -> Graph:
    g = Graph(project="t")
    for f in ("a.py", "b.py", "u1.py", "u2.py", "u3.py"):
        g.add_node(Node(id=f, type=NodeType.PROGRAM, label=f, path=f))
    for u in ("u1.py", "u2.py", "u3.py"):
        g.add_edge(Edge(u, "a.py", EdgeType.IMPORTS))  # a.py is structurally important
    g.add_node(Node(id="session:new", type=NodeType.SESSION, label="new", meta={"date": RECENT}))
    g.add_node(Node(id="session:old", type=NodeType.SESSION, label="old", meta={"date": OLD}))
    g.add_edge(Edge("session:new", "b.py", EdgeType.TOUCHES))  # b.py is recent but unimportant
    g.add_edge(Edge("session:old", "a.py", EdgeType.TOUCHES))
    return g


def _order(res) -> list[str]:
    return [n["id"] for n in res["nodes"]]


def test_focus_recency_zero_byte_identical():
    g = _g_important_vs_recent()
    base = focus(g, "", use_cache=False)
    with_zero = focus(g, "", recency=0.0, use_cache=False)
    assert _order(base) == _order(with_zero)
    assert [n["score"] for n in base["nodes"]] == [n["score"] for n in with_zero["nodes"]]


def test_focus_recency_promotes_recent_over_important():
    g = _g_important_vs_recent()
    plain = _order(focus(g, "", recency=0.0, use_cache=False))
    recent = _order(focus(g, "", recency=0.9, use_cache=False))
    assert plain.index("a.py") < plain.index("b.py")     # importance wins by default
    assert recent.index("b.py") < recent.index("a.py")   # recency lifts b.py above a.py


def test_focus_recency_noop_without_git_history():
    # recency>0 but no sessions -> identical to recency=0 (graceful no-op).
    g = Graph(project="t")
    for f in ("a.py", "b.py"):
        g.add_node(Node(id=f, type=NodeType.PROGRAM, label=f, path=f))
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))
    assert _order(focus(g, "", recency=0.9, use_cache=False)) == \
           _order(focus(g, "", recency=0.0, use_cache=False))


# -- .gitignore matcher -----------------------------------------------------------------------

def _rules(*lines):
    from second_brain.ignore import _compile_gitignore_line
    return [r for r in (_compile_gitignore_line(x) for x in lines) if r is not None]


def test_gitignore_basename_any_depth():
    r = _rules("*.log")
    assert gitignored("a.log", False, r)
    assert gitignored("deep/dir/b.log", False, r)
    assert not gitignored("a.txt", False, r)


def test_gitignore_anchored_root_only():
    r = _rules("/build")
    assert gitignored("build", True, r)
    assert gitignored("build/out.js", False, r)        # contents under the matched dir
    assert not gitignored("src/build", True, r)        # anchored: only at root


def test_gitignore_dir_only():
    r = _rules("cache/")
    assert gitignored("x/cache", True, r)              # a directory named cache
    assert not gitignored("x/cache", False, r)         # a FILE named cache is not matched


def test_gitignore_negation_last_wins():
    r = _rules("*.log", "!keep.log")
    assert gitignored("debug.log", False, r)
    assert not gitignored("keep.log", False, r)        # re-included by the negation


def test_gitignore_doublestar():
    r = _rules("a/**/c.txt")
    assert gitignored("a/c.txt", False, r)
    assert gitignored("a/b/d/c.txt", False, r)
    assert not gitignored("z/c.txt", False, r)


def test_gitignore_comments_and_blanks_skipped():
    r = _rules("# a comment", "", "   ", "*.tmp")
    assert len(r) == 1
    assert gitignored("x.tmp", False, r)


def test_load_gitignore_rules_reads_file(tmp_path):
    (tmp_path / ".gitignore").write_text("*.env\nbuild/\n# c\n", encoding="utf-8")
    rules = load_gitignore_rules(tmp_path)
    assert len(rules) == 2
    assert load_gitignore_rules(tmp_path / "nope").__class__ is list  # missing -> []
    assert load_gitignore_rules(tmp_path / "nope") == []


# -- iter_files + build integration -----------------------------------------------------------

def _tree(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.env").write_text("TOKEN=1\n", encoding="utf-8")
    (tmp_path / "tmpdir").mkdir()
    (tmp_path / "tmpdir" / "junk.py").write_text("y = 2\n", encoding="utf-8")


def test_iter_files_without_gitrules_includes_everything(tmp_path):
    _tree(tmp_path)
    rels = iter_files(tmp_path, [])
    assert "secret.env" in rels and "tmpdir/junk.py" in rels


def test_iter_files_with_gitrules_excludes(tmp_path):
    _tree(tmp_path)
    rules = _rules("*.env", "tmpdir/")
    rels = iter_files(tmp_path, [], rules)
    assert "a.py" in rels
    assert "secret.env" not in rels
    assert "tmpdir/junk.py" not in rels          # the whole dir is pruned


def test_build_respects_gitignore_when_configured(tmp_path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.env\ntmpdir/\n", encoding="utf-8")
    (tmp_path / ".secondbrain.json").write_text(
        json.dumps({"respect_gitignore": True}), encoding="utf-8"
    )
    g = build_graph(tmp_path)
    assert "a.py" in g.nodes
    assert "secret.env" not in g.nodes
    assert "tmpdir/junk.py" not in g.nodes


def test_build_ignores_gitignore_by_default(tmp_path):
    # Same tree + .gitignore but NO opt-in config -> .gitignore is NOT honored (byte-identical).
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.env\ntmpdir/\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert "secret.env" in g.nodes
    assert "tmpdir/junk.py" in g.nodes


# -- config -----------------------------------------------------------------------------------

def test_config_respect_gitignore_parsing(tmp_path):
    assert load_config(tmp_path).respect_gitignore is False  # absent -> off
    (tmp_path / ".secondbrain.json").write_text(
        json.dumps({"respect_gitignore": True}), encoding="utf-8"
    )
    assert load_config(tmp_path).respect_gitignore is True
    # only-flag config (no "classify" block) still parses the flag
    (tmp_path / ".secondbrain.json").write_text(
        json.dumps({"respect_gitignore": True, "classify": {"mode": "replace"}}), encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.respect_gitignore is True and cfg.mode == "replace"
