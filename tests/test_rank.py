"""Tests for the PageRank ranking layer."""

from __future__ import annotations

from second_brain import rank
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def _n(nid: str, t: NodeType = NodeType.PROGRAM) -> Node:
    return Node(id=nid, type=t, label=nid, path=nid)


def _chain_graph() -> Graph:
    """a -> b -> c and a -> c (imports). c is the most depended-on."""
    g = Graph(project="t")
    for x in ("a", "b", "c"):
        g.add_node(_n(x))
    g.add_edge(Edge("a", "b", EdgeType.IMPORTS))
    g.add_edge(Edge("b", "c", EdgeType.IMPORTS))
    g.add_edge(Edge("a", "c", EdgeType.IMPORTS))
    return g


def test_scores_sum_to_one():
    g = _chain_graph()
    rk = rank.pagerank(g)
    assert abs(sum(rk.values()) - 1.0) < 1e-6


def test_empty_graph_returns_empty():
    assert rank.pagerank(Graph(project="e")) == {}


def test_most_depended_on_ranks_highest():
    g = _chain_graph()
    rk = rank.pagerank(g)
    # c is imported by both a and b -> highest; a imports others, depended on by none -> lowest.
    assert rk["c"] > rk["b"] > rk["a"]


def test_dangling_node_conserves_mass():
    # 'sink' has no out-edges (dangling); mass must not leak.
    g = Graph(project="t")
    g.add_node(_n("a"))
    g.add_node(_n("sink"))
    g.add_edge(Edge("a", "sink", EdgeType.IMPORTS))
    rk = rank.pagerank(g)
    assert abs(sum(rk.values()) - 1.0) < 1e-6


def test_deterministic():
    g = _chain_graph()
    assert rank.pagerank(g) == rank.pagerank(g)


def test_personalised_concentrates_on_seed():
    g = _chain_graph()
    glob = rank.pagerank(g)
    pers = rank.personalised(g, ["a"])
    # Seeding the restart on 'a' must raise a's relative score vs the global ranking.
    assert pers["a"] > glob["a"]


def test_top_k_sorted_and_filtered():
    g = _chain_graph()
    g.add_node(_n("area:x", NodeType.AREA))
    top2 = rank.top(g, 2, predicate=lambda node: node.type is not NodeType.AREA)
    assert [nid for nid, _ in top2] == ["c", "b"]
    assert all(nid != "area:x" for nid, _ in top2)


def test_top_reuses_precomputed_scores():
    g = _chain_graph()
    rk = rank.pagerank(g)
    assert rank.top(g, 1, scores=rk)[0][0] == "c"
