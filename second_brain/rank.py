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

from second_brain import memo
from second_brain.model import EdgeType, Graph, Node

# Importance flows along knowledge edges (A imports/references B -> B gains importance).
KNOWLEDGE: tuple[EdgeType, ...] = (EdgeType.IMPORTS, EdgeType.REFERENCES)


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
    if not graph.nodes:
        return {}
    if not personalization:
        # The global ranking depends on the graph alone: computed once per loaded graph.
        key = ("pagerank", relations, damping, max_iter, tol)
        return dict(memo.per_graph(graph, key, lambda: _iterate(
            graph, relations, damping, max_iter, tol, None)))
    return _iterate(graph, relations, damping, max_iter, tol, personalization)


def _prepared(graph: Graph, relations: tuple[EdgeType, ...]) -> tuple[
        list[str], list[int], list[tuple[int, int, list[int]]]]:
    """Sorted node ids, dangling positions and ``(position, outdegree, targets)`` per source —
    integer positions instead of string keys, built once per graph."""
    def build() -> tuple[list[str], list[int], list[tuple[int, int, list[int]]]]:
        nodes = sorted(graph.nodes)
        pos = {nid: i for i, nid in enumerate(nodes)}
        out: list[list[int]] = [[] for _ in nodes]
        for e in graph.edges:
            if e.type in relations:
                s, t = pos.get(e.source), pos.get(e.target)
                if s is not None and t is not None:
                    out[s].append(t)
        dangling = [i for i, o in enumerate(out) if not o]
        sources = [(i, len(o), o) for i, o in enumerate(out) if o]
        return nodes, dangling, sources
    return memo.per_graph(graph, ("pagerank-adj", relations), build)


def _iterate(
    graph: Graph, relations: tuple[EdgeType, ...], damping: float, max_iter: int, tol: float,
    personalization: dict[str, float] | None,
) -> dict[str, float]:
    """The power iteration. Same operations in the same order as the former dict version
    (sorted nodes, edges in graph order), so the scores are bit-identical — only list positions
    replace string-keyed lookups."""
    nodes, dangling_at, sources = _prepared(graph, relations)
    n = len(nodes)

    if personalization:
        p = [max(0.0, float(personalization.get(nid, 0.0))) for nid in nodes]
        s = sum(p)
        p = [v / s for v in p] if s > 0 else [1.0 / n] * n
    else:
        p = [1.0 / n] * n

    rank = [1.0 / n] * n
    for _ in range(max_iter):
        dangling = sum(rank[i] for i in dangling_at)
        # Teleport + dangling mass, both distributed by the restart vector.
        new = [(1.0 - damping) * pi + damping * dangling * pi for pi in p]
        for src, d, targets in sources:
            share = damping * rank[src] / d
            for tgt in targets:
                new[tgt] += share
        err = sum(abs(a - b) for a, b in zip(new, rank, strict=True))
        rank = new
        if err < tol:
            break
    return dict(zip(nodes, rank, strict=True))


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
