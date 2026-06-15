"""PageRank over the knowledge graph: structural importance, not just link count.

Pure-Python, zero-dependency, deterministic. A node ranks high when the *important* files
depend on it (imports/references flowing in), recursively — so a module that the core files
import outranks one imported by many trivial files. This is a better "what matters here?"
signal than raw degree, and the same engine powers task-aware ``focus`` via a personalised
restart vector.

Handles dangling nodes (no out-edges) by redistributing their mass through the restart
distribution, so probability mass is conserved and the scores sum to ~1.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from second_brain.model import EdgeType, Graph, Node

# Importance flows along knowledge edges (A imports/references B -> B gains importance).
KNOWLEDGE: tuple[EdgeType, ...] = (EdgeType.IMPORTS, EdgeType.REFERENCES)


def _out_adjacency(graph: Graph, relations: tuple[EdgeType, ...]) -> dict[str, list[str]]:
    """Directed out-edges per node id, restricted to ``relations`` (targets must be real nodes)."""
    out: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
    for e in graph.edges:
        if e.type in relations and e.source in out and e.target in graph.nodes:
            out[e.source].append(e.target)
    return out


def pagerank(
    graph: Graph,
    *,
    relations: tuple[EdgeType, ...] = KNOWLEDGE,
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-9,
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """Return ``{node_id: score}`` (scores sum to ~1). Deterministic.

    ``personalization`` is an optional restart distribution (the teleport and dangling mass go
    here instead of uniform) — pass it to bias the walk toward seed nodes (personalised PageRank).
    Non-negative weights; if it sums to zero it is ignored (falls back to uniform).
    """
    nodes = sorted(graph.nodes)
    n = len(nodes)
    if n == 0:
        return {}

    out = _out_adjacency(graph, relations)
    outdeg = {nid: len(out[nid]) for nid in nodes}

    if personalization:
        p = {nid: max(0.0, float(personalization.get(nid, 0.0))) for nid in nodes}
        s = sum(p.values())
        p = {nid: (v / s if s > 0 else 1.0 / n) for nid, v in p.items()} if s > 0 \
            else {nid: 1.0 / n for nid in nodes}
    else:
        p = {nid: 1.0 / n for nid in nodes}

    rank = {nid: 1.0 / n for nid in nodes}
    for _ in range(max_iter):
        dangling = sum(rank[nid] for nid in nodes if outdeg[nid] == 0)
        # Teleport + dangling mass, both distributed by the restart vector.
        new = {nid: (1.0 - damping) * p[nid] + damping * dangling * p[nid] for nid in nodes}
        for src in nodes:
            d = outdeg[src]
            if d:
                share = damping * rank[src] / d
                for tgt in out[src]:
                    new[tgt] += share
        err = sum(abs(new[nid] - rank[nid]) for nid in nodes)
        rank = new
        if err < tol:
            break
    return rank


def personalised(
    graph: Graph,
    seeds: dict[str, float] | list[str] | set[str],
    **kwargs: Any,
) -> dict[str, float]:
    """Personalised PageRank: bias the restart toward ``seeds`` (the task's anchor nodes).

    ``seeds`` may be a weight map ``{id: weight}`` or any iterable of ids (uniform weight).
    """
    if isinstance(seeds, dict):
        vec = {k: float(v) for k, v in seeds.items()}
    else:
        vec = {s: 1.0 for s in seeds}
    return pagerank(graph, personalization=vec, **kwargs)


def top(
    graph: Graph,
    k: int,
    *,
    scores: dict[str, float] | None = None,
    predicate: Callable[[Node], bool] | None = None,
    **kwargs: Any,
) -> list[tuple[str, float]]:
    """Top-``k`` ``(node_id, score)`` by score desc, tie-broken by id (deterministic).

    ``scores`` reuses a precomputed ranking (avoids recomputing); ``predicate`` is an optional
    ``callable(Node) -> bool`` filter (e.g. only file-backed nodes). Ids absent from the graph are
    always dropped, so a reused ``scores`` from a larger graph can't leak phantom nodes.
    """
    rk = scores if scores is not None else pagerank(graph, **kwargs)
    items = [(nid, s) for nid, s in rk.items() if nid in graph.nodes
             and (predicate is None or predicate(graph.nodes[nid]))]
    ranked = sorted(items, key=lambda kv: (-kv[1], kv[0]))
    return ranked[: max(0, k)]


__all__ = ["KNOWLEDGE", "pagerank", "personalised", "top"]
