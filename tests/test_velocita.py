"""0.10.2: the speed-ups change no result — same scores, same signature, same decisions."""

from __future__ import annotations

import random

from second_brain import bm25, freshness, memo, rank
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _reference_pagerank(graph, damping=0.85, max_iter=100, tol=1e-9, personalization=None):
    """The 0.10.1 implementation, verbatim in substance (dict-keyed)."""
    nodes = sorted(graph.nodes)
    n = len(nodes)
    out = {nid: [] for nid in graph.nodes}
    for e in graph.edges:
        if e.type in rank.KNOWLEDGE and e.source in out and e.target in graph.nodes:
            out[e.source].append(e.target)
    outdeg = {nid: len(out[nid]) for nid in nodes}
    if personalization:
        p = {nid: max(0.0, float(personalization.get(nid, 0.0))) for nid in nodes}
        s = sum(p.values())
        p = {nid: v / s for nid, v in p.items()} if s > 0 else {nid: 1.0 / n for nid in nodes}
    else:
        p = {nid: 1.0 / n for nid in nodes}
    r = {nid: 1.0 / n for nid in nodes}
    for _ in range(max_iter):
        dangling = sum(r[nid] for nid in nodes if outdeg[nid] == 0)
        new = {nid: (1.0 - damping) * p[nid] + damping * dangling * p[nid] for nid in nodes}
        for src in nodes:
            d = outdeg[src]
            if d:
                share = damping * r[src] / d
                for tgt in out[src]:
                    new[tgt] += share
        err = sum(abs(new[nid] - r[nid]) for nid in nodes)
        r = new
        if err < tol:
            break
    return r


def _random_graph(seed: int, n: int = 400, m: int = 1200) -> Graph:
    rnd = random.Random(seed)
    g = Graph("t")
    ids = [f"f{i:04d}.py" for i in range(n)]
    rnd.shuffle(ids)                       # insertion order != sorted order
    for i in ids:
        g.add_node(Node(id=i, type=NodeType.PROGRAM, label=i, path=i))
    types = [EdgeType.IMPORTS, EdgeType.REFERENCES, EdgeType.BELONGS_TO]
    for _ in range(m):
        g.add_edge(Edge(rnd.choice(ids), rnd.choice(ids), rnd.choice(types)))
    return g


def test_pagerank_is_bit_identical_to_the_previous_implementation():
    for seed in range(5):
        g = _random_graph(seed)
        assert rank.pagerank(g) == _reference_pagerank(g)
        seeds = {nid: float(i + 1) for i, nid in enumerate(sorted(g.nodes)[:7])}
        assert rank.personalised(g, seeds) == _reference_pagerank(g, personalization=seeds)


def test_global_pagerank_is_computed_once_per_graph_and_redone_when_it_changes(monkeypatch):
    memo.clear()
    g = _random_graph(1)
    calls = {"n": 0}
    real = rank._iterate

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(rank, "_iterate", counting)
    first = rank.pagerank(g)
    first["f0000.py"] = -1.0                      # a caller mutating its copy changes nothing
    assert rank.pagerank(g)["f0000.py"] != -1.0
    assert calls["n"] == 1
    g.add_edge(Edge("f0001.py", "f0002.py", EdgeType.IMPORTS, {"x": 1}))
    g.add_edge(Edge("f0003.py", "f0004.py", EdgeType.REFERENCES))
    assert rank.pagerank(g) == _reference_pagerank(g)
    assert calls["n"] == 2


def test_bm25_with_postings_scores_exactly_like_scoring_every_document():
    rnd = random.Random(7)
    words = ["backup", "nas", "robocopy", "lock", "graph", "focus", "test", "py", "doc", "x1"]
    docs = {f"d{i}": " ".join(rnd.choice(words) for _ in range(rnd.randint(1, 9)))
            for i in range(300)}
    idx = bm25.BM25(docs)
    for q in ("backup nas", "robocopy lock lock", "assente", "py test x1"):
        toks = bm25.tokenize(q)
        brute = {d: s for d in docs if (s := idx.score(toks, d)) > 0.0}
        got = idx.scores(toks)
        assert got == brute and list(got) == list(brute)   # same values, same order


def test_signature_with_confirm_equals_the_plain_signature(tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.md").write_text(f"# {i}\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    plain = freshness.fast_signature(tmp_path)
    assert freshness.fast_signature(tmp_path, confirm=plain) == plain
    wrong = {k: "0:0" for k in plain}             # disagreeing listing values are re-stat'ed
    assert freshness.fast_signature(tmp_path, confirm=wrong) == plain


def test_a_stale_store_nobody_else_rebuilt_is_walked_once_not_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    freshness.load_or_refresh(tmp_path)
    (tmp_path / "b.md").write_text("# b\n", encoding="utf-8")
    walks = {"n": 0}
    real = freshness.fast_signature

    def counting(*a, **k):
        walks["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(freshness, "fast_signature", counting)
    g = freshness.load_or_refresh(tmp_path, refresh=True)
    assert "b.md" in g.nodes
    assert walks["n"] == 1        # the check; the rebuild's own walk is index_cached's


def test_a_first_build_that_takes_long_answers_in_costruzione_then_serves_it(tmp_path, monkeypatch):
    """The first build of a big project runs in the background; the call does not hang on it."""
    import threading

    from second_brain import mcp_server

    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    monkeypatch.setenv("SECOND_BRAIN_BUILD_WAIT", "0.2")
    mcp_server.clear_graph_cache()
    gate_open = threading.Event()
    real = mcp_server.load_or_refresh

    def slow(root, **k):
        assert gate_open.wait(10)
        return real(root, **k)
    monkeypatch.setattr(mcp_server, "load_or_refresh", slow)
    import pytest
    with pytest.raises(RuntimeError, match="si sta costruendo"):
        mcp_server._graph(str(tmp_path))
    with pytest.raises(RuntimeError, match="si sta costruendo"):  # still going: no second build
        mcp_server._graph(str(tmp_path))
    assert len([t for t in threading.enumerate() if t.name.startswith("second-brain-build")]) == 1
    gate_open.set()
    g = mcp_server._graph(str(tmp_path))
    assert "a.md" in g.nodes and str(tmp_path) not in mcp_server._BUILDING


def test_a_small_first_build_answers_within_the_same_call(tmp_path):
    from second_brain import mcp_server

    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    mcp_server.clear_graph_cache()
    assert "a.md" in mcp_server._graph(str(tmp_path)).nodes
