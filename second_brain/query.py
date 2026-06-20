"""Low-token query layer over the project graph.

The whole point of Second Brain is that an assistant *queries* the graph and gets compact,
budgeted answers — instead of re-reading whole files. Every function here returns a small,
plain-data structure (ids, types, short labels, counts, sizes) — never file contents — so a
session bootstrap or a targeted question costs a few hundred to a couple thousand tokens, not
tens of thousands. Pure functions over a :class:`~second_brain.model.Graph`; no I/O, no deps.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from second_brain import bm25, budget, communities, rank
from second_brain import recency as recency_mod
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

KNOWLEDGE = (EdgeType.IMPORTS, EdgeType.REFERENCES)

# Relations that count as a real dependency for impact analysis. BELONGS_TO (area membership)
# and TOUCHES (git sessions) are deliberately excluded: they would make every file "depend on"
# its area / every commit, drowning the signal.
IMPACT_RELATIONS = (EdgeType.IMPORTS, EdgeType.REFERENCES, EdgeType.MENTIONS)


__all__ = ["project_map", "find", "neighbors", "backbone", "subgraph", "impact",
           "impact_diff", "why", "focus", "clear_focus_cache"]


def _area_of(path: str | None) -> str:
    if not path:
        return "(root)"
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def _degrees(graph: Graph) -> dict[str, int]:
    """Knowledge degree (imports/references only) per node id."""
    deg: dict[str, int] = {}
    for e in graph.edges:
        if e.type in KNOWLEDGE:
            deg[e.source] = deg.get(e.source, 0) + 1
            deg[e.target] = deg.get(e.target, 0) + 1
    return deg


def project_map(graph: Graph, *, top: int = 8) -> dict[str, Any]:
    """Compact project digest — the cheap thing to load when work starts.

    Returns areas (with file counts, total size, dominant types), type/edge tallies, the
    most-connected files, and orphan/broken counts. Lists are capped by ``top``.
    """
    files = sorted((n for n in graph.nodes.values()
                    if n.path is not None and n.type is not NodeType.AREA), key=lambda n: n.id)
    areas: dict[str, dict] = {}
    for n in files:
        a = _area_of(n.path)
        e = areas.setdefault(a, {"files": 0, "size": 0, "types": {}})
        e["files"] += 1
        sz = int(n.meta.get("size", 0))
        e["size"] += sz
        e["types"][n.type.value] = e["types"].get(n.type.value, 0) + sz

    def _area_row(name: str, e: dict[str, Any]) -> dict[str, Any]:
        # Tie-break by name so equal-size types order deterministically (not by insertion).
        types = sorted(e["types"].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        return {"area": name, "files": e["files"], "size": e["size"],
                "top_types": [t for t, _ in types]}

    area_rows = sorted((_area_row(a, e) for a, e in areas.items()),
                       key=lambda r: (-r["size"], r["area"]))[:top]

    deg = _degrees(graph)
    # Tie-break by id: equal-degree nodes must order deterministically across runs.
    most = sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))
    most_connected = []
    for nid, d in most[:top]:
        n = graph.nodes.get(nid)
        if n is not None:
            most_connected.append({"id": nid, "type": n.type.value, "degree": d})

    counts = graph.counts()
    broken = sum(len(n.meta.get("broken_refs", [])) for n in graph.nodes.values())
    orphans = sum(1 for n in files if not deg.get(n.id))
    n_communities = len(set(communities.detect(graph).values()))
    return {
        "project": graph.project,
        "files": len(files),
        "areas": len(areas),
        "links": len(graph.edges),
        "size": sum(int(n.meta.get("size", 0)) for n in files),
        "node_types": counts["nodes"],
        "edge_types": counts["edges"],
        "communities": n_communities,
        "by_area": area_rows,
        "most_connected": most_connected,
        "orphans": orphans,
        "broken_refs": broken,
    }


def find(graph: Graph, query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Return file/entity nodes whose label or path contains ``query`` (case-insensitive).

    Returns *every* match by default so the count is always truthful — a memory tool must never
    silently drop results (or under-count whole families). Pass ``limit`` to cap the returned
    list; the caller is responsible for reporting the true total alongside any capped view.
    """
    q = query.lower().strip()
    if not q:
        return []
    hits = [n for n in graph.nodes.values()
            if n.type is not NodeType.AREA
            and (q in n.label.lower() or (n.path and q in n.path.lower()))]
    # Sort by id before capping so the returned subset is deterministic, not insertion-order.
    hits.sort(key=lambda n: n.id)
    rows = [{"id": n.id, "type": n.type.value, "path": n.path} for n in hits]
    return rows if limit is None else rows[: max(0, limit)]


def neighbors(graph: Graph, node_id: str, *, limit: int = 0) -> dict[str, Any] | None:
    """Return a node and its incoming/outgoing connections (compact). None if unknown.

    ``limit`` > 0 caps each direction to that many rows (deterministic insertion order) and reports
    the true ``outgoing_total`` / ``incoming_total`` + a ``truncated`` flag — so a god-node with
    thousands of edges can't flood the context. ``limit`` <= 0 (default) returns every edge.
    """
    n = graph.nodes.get(node_id)
    if n is None:
        return None

    def _row(other: str, etype: str) -> dict[str, Any]:
        t = graph.nodes[other].type.value if other in graph.nodes else "?"
        return {"id": other, "type": t, "edge": etype}

    out = [_row(e.target, e.type.value) for e in graph.edges if e.source == node_id]
    inc = [_row(e.source, e.type.value) for e in graph.edges if e.target == node_id]
    out_total, inc_total = len(out), len(inc)
    truncated = False
    if limit and limit > 0:
        if out_total > limit:
            out, truncated = out[:limit], True
        if inc_total > limit:
            inc, truncated = inc[:limit], True
    return {
        "id": n.id, "type": n.type.value, "path": n.path,
        "size": int(n.meta.get("size", 0)),
        "description": n.description,
        "broken_refs": n.meta.get("broken_refs", []),
        "outgoing": out,
        "incoming": inc,
        "outgoing_total": out_total,
        "incoming_total": inc_total,
        "truncated": truncated,
    }


def backbone(graph: Graph, *, keep_decisions: bool = True) -> Graph:
    """Return a compact 'backbone' of a large graph, light enough to render.

    Keeps area nodes, every file with a knowledge edge (imports/references), and decisions.
    Isolated data/config files (no knowledge edge) are dropped from the render but counted on
    their area node (``meta['hidden']``) — so the whole project is still represented at a glance,
    and you drill into a sub-area's full detail by pointing the tool at that subfolder.
    """
    deg = _degrees(graph)
    keep: set[str] = set()
    for n in graph.nodes.values():
        is_dec = keep_decisions and n.type is NodeType.DECISION
        if n.type is NodeType.AREA or deg.get(n.id) or is_dec:
            keep.add(n.id)
    out = Graph(project=graph.project)
    hidden: dict[str, int] = {}
    for n in graph.nodes.values():
        if n.id in keep:
            out.add_node(Node(id=n.id, type=n.type, label=n.label, path=n.path,
                              description=n.description, meta=dict(n.meta)))
        elif n.path is not None:
            aid = f"area:{_area_of(n.path)}"
            hidden[aid] = hidden.get(aid, 0) + 1
    for aid, cnt in hidden.items():
        if aid in out.nodes:
            out.nodes[aid].meta["hidden"] = cnt
    for e in graph.edges:
        if e.source in keep and e.target in keep:
            out.add_edge(Edge(e.source, e.target, e.type))
    return out


def subgraph(graph: Graph, node_id: str, *, hops: int = 1) -> dict[str, Any]:
    """Return a small subgraph around ``node_id`` within ``hops`` (nodes + edges, compact)."""
    if node_id not in graph.nodes:
        return {"nodes": [], "edges": []}
    frontier = {node_id}
    seen = {node_id}
    for _ in range(max(0, hops)):
        nxt: set[str] = set()
        for e in graph.edges:
            # Guard against edges that reference an id with no node (would KeyError below).
            if e.source in frontier and e.target not in seen and e.target in graph.nodes:
                nxt.add(e.target)
            if e.target in frontier and e.source not in seen and e.source in graph.nodes:
                nxt.add(e.source)
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    nodes = [{"id": nid, "type": graph.nodes[nid].type.value, "label": graph.nodes[nid].label}
             for nid in sorted(seen)]
    edges = [{"source": e.source, "target": e.target, "type": e.type.value}
             for e in graph.edges if e.source in seen and e.target in seen]
    return {"nodes": nodes, "edges": edges}


def _impact_walk(
    graph: Graph,
    start: str,
    *,
    incoming: bool,
    max_depth: int,
    relations: tuple[EdgeType, ...],
    cap: int,
) -> tuple[dict[int, list[dict[str, Any]]], bool]:
    """BFS the dependency graph from ``start``, grouping reached nodes by depth.

    ``incoming=True`` walks edges *into* nodes (upstream: who depends on start); ``incoming=False``
    walks edges *out of* nodes (downstream: what start depends on). Deterministic (each level is
    id/edge-sorted) and capped per depth — the cap bounds both the output and the next frontier.
    """
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in graph.edges:
        if e.type not in relations:
            continue
        if incoming:
            adj.setdefault(e.target, []).append((e.source, e.type.value))
        else:
            adj.setdefault(e.source, []).append((e.target, e.type.value))

    seen = {start}
    frontier = [start]
    groups: dict[int, list[dict[str, Any]]] = {}
    truncated = False
    depth = 1
    while frontier and depth <= max_depth:
        level: dict[str, dict[str, Any]] = {}
        for node in frontier:
            for other, etype in adj.get(node, ()):
                if other in seen or other in level:
                    continue
                n = graph.nodes.get(other)
                level[other] = {
                    "depth": depth, "id": other,
                    "type": n.type.value if n else "?",
                    "path": n.path if n else None,
                    "edge": etype, "via": node,
                }
        entries = sorted(level.values(), key=lambda r: (r["id"], r["edge"]))
        # Mark every node reached this level as seen — even ones the cap drops — so a capped
        # node cannot reappear at a deeper level (each node is reported at its shallowest depth).
        for nid in level:
            seen.add(nid)
        if len(entries) > cap:
            entries = entries[:cap]
            truncated = True
        if entries:
            groups[depth] = entries
        frontier = [r["id"] for r in entries]
        depth += 1
    return groups, truncated


def _rank_and_budget(
    graph: Graph,
    groups: dict[int, list[dict[str, Any]]],
    *,
    budget_tokens: int,
    base_truncated: bool,
) -> tuple[dict[int, list[dict[str, Any]]], bool]:
    """Annotate each impacted entry with its incident ``degree`` and, when ``budget_tokens`` > 0,
    keep only the most useful ones within the token budget — shallowest first, then most-connected
    (a hub dependent matters more to review), then id. Deterministic. Default (0) leaves the
    grouping untouched and only adds ``degree``."""
    flat: list[dict[str, Any]] = []
    for depth in groups:
        for r in groups[depth]:
            r["degree"] = graph.degree(r["id"])
            flat.append(r)
    if budget_tokens <= 0:
        return groups, base_truncated
    flat.sort(key=lambda r: (r["depth"], -r["degree"], r["id"]))
    kept, _spent, trimmed = budget.fit(
        flat,
        lambda r: budget.node_cost(graph.nodes[r["id"]]) if r["id"] in graph.nodes else 1,
        budget_tokens,
    )
    new_groups: dict[int, list[dict[str, Any]]] = {}
    for r in kept:
        new_groups.setdefault(r["depth"], []).append(r)
    for d in new_groups:
        new_groups[d].sort(key=lambda r: (-r["degree"], r["id"]))
    return new_groups, (base_truncated or trimmed)


def impact(
    graph: Graph,
    node_id: str,
    *,
    direction: str = "both",
    max_depth: int = 2,
    relations: tuple[EdgeType, ...] = IMPACT_RELATIONS,
    cap: int = 200,
    budget_tokens: int = 0,
) -> dict[str, Any]:
    """Impact radius of a node: what breaks if you touch it, and what it depends on.

    ``direction`` in {``up``, ``down``, ``both``}. ``upstream`` = nodes that depend on ``node_id``
    (incoming edges; depth 1 is the direct blast radius). ``downstream`` = nodes ``node_id``
    depends on (outgoing edges). Results are grouped by ``depth`` and capped per depth for safety.
    Returns ``{"exists": False}`` for an unknown node so a caller can distinguish it from "no deps".
    """
    if direction not in ("up", "down", "both"):
        raise ValueError(f"direction must be 'up', 'down' or 'both' (got {direction!r})")
    n = graph.nodes.get(node_id)
    if n is None:
        return {"id": node_id, "exists": False}
    out: dict[str, Any] = {
        "id": node_id, "exists": True, "type": n.type.value, "path": n.path,
        "direction": direction, "max_depth": max_depth,
    }
    if direction in ("up", "both"):
        groups, trunc = _impact_walk(graph, node_id, incoming=True,
                                     max_depth=max_depth, relations=relations, cap=cap)
        groups, trunc = _rank_and_budget(graph, groups, budget_tokens=budget_tokens,
                                         base_truncated=trunc)
        out["upstream"] = groups
        out["upstream_truncated"] = trunc
    if direction in ("down", "both"):
        groups, trunc = _impact_walk(graph, node_id, incoming=False,
                                     max_depth=max_depth, relations=relations, cap=cap)
        groups, trunc = _rank_and_budget(graph, groups, budget_tokens=budget_tokens,
                                         base_truncated=trunc)
        out["downstream"] = groups
        out["downstream_truncated"] = trunc
    return out


def _impact_walk_multi(
    graph: Graph,
    starts: list[str],
    *,
    incoming: bool,
    max_depth: int,
    relations: tuple[EdgeType, ...],
    cap: int,
) -> tuple[dict[int, list[dict[str, Any]]], bool]:
    """Multi-source BFS of the dependency graph from a SET of starts (used by impact_diff).

    Same shape as :func:`_impact_walk` but seeded from several nodes at once and grouping each
    reached node at its shallowest depth across all seeds. All seeds are excluded from results.
    """
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in graph.edges:
        if e.type not in relations:
            continue
        if incoming:
            adj.setdefault(e.target, []).append((e.source, e.type.value))
        else:
            adj.setdefault(e.source, []).append((e.target, e.type.value))

    seen = set(starts)
    frontier = list(starts)
    groups: dict[int, list[dict[str, Any]]] = {}
    truncated = False
    depth = 1
    while frontier and depth <= max_depth:
        level: dict[str, dict[str, Any]] = {}
        for node in frontier:
            for other, etype in adj.get(node, ()):
                if other in seen or other in level:
                    continue
                n = graph.nodes.get(other)
                level[other] = {"depth": depth, "id": other,
                                "type": n.type.value if n else "?",
                                "path": n.path if n else None, "edge": etype, "via": node}
        entries = sorted(level.values(), key=lambda r: (r["id"], r["edge"]))
        for nid in level:
            seen.add(nid)
        if len(entries) > cap:
            entries = entries[:cap]
            truncated = True
        if entries:
            groups[depth] = entries
        frontier = [r["id"] for r in entries]
        depth += 1
    return groups, truncated


def impact_diff(
    graph: Graph,
    changed_paths: list[str],
    *,
    direction: str = "both",
    max_depth: int = 2,
    relations: tuple[EdgeType, ...] = IMPACT_RELATIONS,
    cap: int = 200,
    budget_tokens: int = 0,
) -> dict[str, Any]:
    """Combined blast radius of a set of changed files (e.g. the working-tree diff).

    Walks the impact graph from every changed path that is a node and merges the results, so the
    *current uncommitted changes* show their full reach in one view. ``upstream`` = who depends on
    the changed files (what might break); ``downstream`` = what they depend on. ``unindexed`` lists
    changed paths that aren't graph nodes (new/ignored/data files).
    """
    if direction not in ("up", "down", "both"):
        raise ValueError(f"direction must be 'up', 'down' or 'both' (got {direction!r})")
    seeds = sorted(p for p in changed_paths if p in graph.nodes)
    out: dict[str, Any] = {
        "direction": direction, "max_depth": max_depth,
        "changed": sorted(set(changed_paths)), "seeds": seeds,
        "unindexed": sorted(p for p in set(changed_paths) if p not in graph.nodes),
    }
    if direction in ("up", "both"):
        groups, trunc = _impact_walk_multi(graph, seeds, incoming=True,
                                           max_depth=max_depth, relations=relations, cap=cap)
        groups, trunc = _rank_and_budget(graph, groups, budget_tokens=budget_tokens,
                                         base_truncated=trunc)
        out["upstream"] = groups
        out["upstream_truncated"] = trunc
    if direction in ("down", "both"):
        groups, trunc = _impact_walk_multi(graph, seeds, incoming=False,
                                           max_depth=max_depth, relations=relations, cap=cap)
        groups, trunc = _rank_and_budget(graph, groups, budget_tokens=budget_tokens,
                                         base_truncated=trunc)
        out["downstream"] = groups
        out["downstream_truncated"] = trunc
    present = [out[k] for k in ("upstream", "downstream") if k in out]
    if seeds and present and not any(present):
        out["note"] = ("every impacted node is itself among the changed files "
                       "(seeds are excluded from the results)")
    return out


def community_summary(graph: Graph, *, key_files: int = 5, surprising: int = 10,
                      limit: int = 0) -> dict[str, Any]:
    """The project's real modules - clusters discovered from imports+references (not folders) -
    each with size, cohesion, key files and dominant types, plus the most important cross-module
    bridges. The structural lens, without loading the full report.
    """
    from second_brain import communities as _c
    comm = _c.detect(graph)
    rows = _c.summarize(graph, comm, key_files=key_files)  # largest community first
    total = len(rows)
    truncated = False
    if limit and limit > 0 and total > limit:
        rows, truncated = rows[:limit], True
    return {
        "count": total,
        "shown": len(rows),
        "truncated": truncated,
        "communities": rows,
        "surprising_edges": _c.surprising_edges(graph, comm, top=surprising),
    }

def why(
    graph: Graph,
    source: str,
    target: str,
    *,
    relations: tuple[EdgeType, ...] = KNOWLEDGE,
    max_depth: int = 12,
) -> dict[str, Any]:
    """Shortest path between two nodes over knowledge edges (undirected) — "how are these linked?".

    Returns ``{"exists": False}`` if either id is unknown; ``connected: False`` with an empty path
    if there is no link within ``max_depth``; otherwise the ``path`` (node by node) and the
    ``edges`` along it. Deterministic (neighbours visited in id order, so a tie picks the
    lexicographically smallest path).
    """
    if source not in graph.nodes or target not in graph.nodes:
        return {"exists": False, "source": source, "target": target}
    if source == target:
        n = graph.nodes[source]
        return {"exists": True, "connected": True, "source": source, "target": target,
                "length": 0, "path": [{"id": source, "type": n.type.value}], "edges": []}

    adj: dict[str, set[str]] = {}
    edge_of: dict[tuple[str, str], str] = {}
    for e in graph.edges:
        if e.type in relations:
            adj.setdefault(e.source, set()).add(e.target)
            adj.setdefault(e.target, set()).add(e.source)
            edge_of.setdefault((e.source, e.target), e.type.value)

    prev: dict[str, str | None] = {source: None}
    frontier = [source]
    depth = 0
    while frontier and target not in prev and depth < max_depth:
        nxt: list[str] = []
        for node in frontier:
            for other in sorted(adj.get(node, ())):
                if other not in prev:
                    prev[other] = node
                    nxt.append(other)
        frontier = nxt
        depth += 1

    if target not in prev:
        return {"exists": True, "connected": False, "source": source, "target": target,
                "length": None, "path": [], "edges": []}
    ids: list[str] = []
    cur: str | None = target
    while cur is not None:
        ids.append(cur)
        cur = prev[cur]
    ids.reverse()
    path = [{"id": nid, "type": graph.nodes[nid].type.value} for nid in ids]
    edges = []
    for a, b in zip(ids, ids[1:], strict=False):
        et = edge_of.get((a, b)) or edge_of.get((b, a)) or "?"
        edges.append({"source": a, "target": b, "type": et})
    return {"exists": True, "connected": True, "source": source, "target": target,
            "length": len(ids) - 1, "path": path, "edges": edges}


# -- focus: task-aware, budgeted retrieval -----------------------------------------------------
# The personalised-PageRank scores for a (graph, seeds) pair are cached so repeated focus calls
# in a long-running MCP server don't recompute the walk each time. The key includes a structural
# fingerprint of the edge set (NOT just the edge count) so two different graphs with the same
# project/node/edge counts never collide and serve stale scores after a rebuild. The cache is
# bounded (LRU eviction) so it can't grow without limit across many distinct queries.
_FOCUS_CACHE: OrderedDict[Any, dict[str, float]] = OrderedDict()
_FOCUS_CACHE_MAX = 256


def clear_focus_cache() -> None:
    """Drop the cached personalised-PageRank scores (call after rebuilding in-process)."""
    _FOCUS_CACHE.clear()


def _graph_fingerprint(graph: Graph) -> int:
    """Cheap structural fingerprint of nodes + edges (order-independent, O(nodes+edges)).

    Includes the node-id set, not just edges: isolated nodes (orphans) carry no edge, so an
    edges-only fingerprint would alias two graphs that differ only by an isolated-node turnover
    at equal counts — serving cached scores that silently drop the new node.
    """
    return hash((
        frozenset(graph.nodes),
        frozenset((e.source, e.target, e.type.value) for e in graph.edges),
    ))


def _node_text(node: Node) -> str:
    """The searchable text of a node for lexical ranking: id/path/label/type, a symbol's qualified
    name, and the human description when present."""
    parts = [node.id, node.label, node.type.value]
    if node.path:
        parts.append(node.path)
    qual = node.meta.get("qualname")
    if isinstance(qual, str):
        parts.append(qual)
    if node.description:
        parts.append(node.description)
    return " ".join(parts)


def _focus_seeds(graph: Graph, task: str) -> dict[str, float]:
    """Anchor nodes for a task, weighted by **BM25** lexical relevance over each node's text.

    BM25 (IDF x saturated term-frequency) makes a node carrying the task's *rare, specific* terms a
    far stronger anchor than one matching only ubiquitous tokens — a better restart vector for the
    personalised PageRank than the old token-count. Areas are excluded (containers, not answers); a
    task with no token match yields no seed (focus then falls back to global rank).
    """
    toks = bm25.tokenize(task)
    if not toks:
        return {}
    docs = {nid: _node_text(n) for nid, n in graph.nodes.items() if n.type is not NodeType.AREA}
    return bm25.BM25(docs).scores(toks)


def focus(
    graph: Graph,
    task: str,
    *,
    budget_tokens: int = 2000,
    damping: float = 0.85,
    recency: float = 0.0,
    half_life_days: float = 30.0,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return the minimal high-value subgraph for a task, within a token budget.

    Anchors the task to seed nodes (name/path match), runs **personalised PageRank** from them,
    and fills a token budget with the highest-scoring nodes (seeds first), plus the knowledge
    edges among the chosen nodes. With no seed match it falls back to global importance, so the
    assistant always gets *something* relevant rather than the whole digest.

    ``recency`` (0..1, default 0 = off) blends in a deterministic git-derived recency/frequency
    signal (the ACT-R *base-level* of memory): the final ranking becomes
    ``(1-recency)*importance + recency*recency_score``, so a recently/often-touched file can
    outrank a structurally important but dormant one — recall closer to human memory. ``recency``
    is applied *after* the cached PageRank (it never invalidates the cache); with no git history it
    is a no-op. ``half_life_days`` sets how fast the recency weight decays (default 30 days).
    """
    seeds = _focus_seeds(graph, task)
    fallback = not seeds
    key = (graph.project, len(graph.nodes), _graph_fingerprint(graph),
           frozenset(seeds.items()), round(damping, 6))
    scores = _FOCUS_CACHE.get(key) if use_cache else None
    if scores is None:
        scores = (rank.personalised(graph, seeds, damping=damping) if seeds
                  else rank.pagerank(graph, damping=damping))
        if use_cache:
            _FOCUS_CACHE[key] = scores
            _FOCUS_CACHE.move_to_end(key)
            while len(_FOCUS_CACHE) > _FOCUS_CACHE_MAX:
                _FOCUS_CACHE.popitem(last=False)  # evict oldest (LRU)
    elif use_cache:
        _FOCUS_CACHE.move_to_end(key)  # mark as recently used

    # Recency blend (opt-in). Applied post-cache so it never affects the stored PageRank; with
    # recency=0 or no git sessions, rank_scores is exactly scores -> byte-identical ordering.
    rank_scores = scores
    if recency > 0:
        rec = recency_mod.recency_scores(graph, half_life_days=half_life_days)
        if rec:
            rank_scores = recency_mod.blend(scores, rec, recency)

    ranked = sorted(
        ((nid, s) for nid, s in rank_scores.items()
         if nid in graph.nodes and graph.nodes[nid].type is not NodeType.AREA),
        key=lambda kv: (-kv[1], kv[0]),
    )
    seed_ids = set(seeds)
    order = ([nid for nid, _ in ranked if nid in seed_ids]
             + [nid for nid, _ in ranked if nid not in seed_ids])

    chosen: list[str] = []
    seen: set[str] = set()
    spent = 0
    for nid in order:
        cost = budget.node_cost(graph.nodes[nid])
        if chosen and spent + cost > budget_tokens:
            break
        chosen.append(nid)
        seen.add(nid)
        spent += cost

    nodes_out = [{"id": nid, "type": graph.nodes[nid].type.value,
                  "path": graph.nodes[nid].path, "score": round(rank_scores[nid], 6),
                  "seed": nid in seed_ids}
                 for nid in chosen]
    edges_out = [{"source": e.source, "target": e.target, "type": e.type.value}
                 for e in graph.edges
                 if e.type in KNOWLEDGE and e.source in seen and e.target in seen]
    return {
        "task": task,
        "seeds": sorted(seeds),
        "fallback": fallback,
        "recency": recency if recency > 0 else 0.0,
        "budget_tokens": budget_tokens,
        "token_estimate": spent,
        "nodes": nodes_out,
        "edges": edges_out,
    }


def attach_signatures(graph: Graph, root: str, result: dict[str, Any], *,
                      budget_tokens: int = 600, per_file: int = 8) -> dict[str, Any]:
    """Enrich a ``focus`` result with the key symbol signatures of its top Python files.

    Reads (on demand, read-only) the source of each chosen ``.py`` file in rank order and appends
    its top function/class signatures — the API an assistant needs without opening the files —
    until ``budget_tokens`` is spent. Adds ``signatures`` = ``{file_id: [{signature, line, kind,
    depth}]}``. Python only (stdlib ``ast``); non-Python and unreadable files are skipped.
    """
    from pathlib import Path

    from second_brain import symbols as _sym
    root_p = Path(root)
    sigs: dict[str, list[dict[str, Any]]] = {}
    spent = 0
    for n in result.get("nodes", []):
        node = graph.nodes.get(n["id"])
        if (node is None or node.path is None or not node.path.endswith(".py")
                or node.type is not NodeType.PROGRAM):
            continue
        try:
            src = (root_p / node.path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rows: list[dict[str, Any]] = []
        for s in _sym.extract_symbols(src)[:per_file]:
            cost = budget.text_cost(s.signature)
            if budget_tokens > 0 and (sigs or rows) and spent + cost > budget_tokens:
                break
            rows.append({"signature": s.signature, "line": s.line,
                         "kind": s.kind, "depth": s.depth})
            spent += cost
        if rows:
            sigs[node.id] = rows
        if budget_tokens > 0 and spent >= budget_tokens:
            break
    result["signatures"] = sigs
    return result
