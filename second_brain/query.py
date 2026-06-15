"""Low-token query layer over the project graph.

The whole point of Second Brain is that an assistant *queries* the graph and gets compact,
budgeted answers — instead of re-reading whole files. Every function here returns a small,
plain-data structure (ids, types, short labels, counts, sizes) — never file contents — so a
session bootstrap or a targeted question costs a few hundred to a couple thousand tokens, not
tens of thousands. Pure functions over a :class:`~second_brain.model.Graph`; no I/O, no deps.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from second_brain import communities, rank
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

KNOWLEDGE = (EdgeType.IMPORTS, EdgeType.REFERENCES)

# Relations that count as a real dependency for impact analysis. BELONGS_TO (area membership)
# and TOUCHES (git sessions) are deliberately excluded: they would make every file "depend on"
# its area / every commit, drowning the signal.
IMPACT_RELATIONS = (EdgeType.IMPORTS, EdgeType.REFERENCES, EdgeType.MENTIONS)


__all__ = ["project_map", "find", "neighbors", "backbone", "subgraph", "impact",
           "focus", "clear_focus_cache"]


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


def neighbors(graph: Graph, node_id: str) -> dict[str, Any] | None:
    """Return a node and its incoming/outgoing connections (compact). None if unknown."""
    n = graph.nodes.get(node_id)
    if n is None:
        return None

    def _row(other: str, etype: str) -> dict[str, Any]:
        t = graph.nodes[other].type.value if other in graph.nodes else "?"
        return {"id": other, "type": t, "edge": etype}

    out = [_row(e.target, e.type.value) for e in graph.edges if e.source == node_id]
    inc = [_row(e.source, e.type.value) for e in graph.edges if e.target == node_id]
    return {
        "id": n.id, "type": n.type.value, "path": n.path,
        "size": int(n.meta.get("size", 0)),
        "description": n.description,
        "broken_refs": n.meta.get("broken_refs", []),
        "outgoing": out,
        "incoming": inc,
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


def impact(
    graph: Graph,
    node_id: str,
    *,
    direction: str = "both",
    max_depth: int = 2,
    relations: tuple[EdgeType, ...] = IMPACT_RELATIONS,
    cap: int = 200,
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
        out["upstream"] = groups
        out["upstream_truncated"] = trunc
    if direction in ("down", "both"):
        groups, trunc = _impact_walk(graph, node_id, incoming=False,
                                     max_depth=max_depth, relations=relations, cap=cap)
        out["downstream"] = groups
        out["downstream_truncated"] = trunc
    return out


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


def _task_tokens(task: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9_]+", task.lower()) if len(t) >= 3]


def _focus_seeds(graph: Graph, task: str) -> dict[str, float]:
    """Anchor nodes for a task: file/entity nodes whose label or path contains a task token.

    Weight = number of distinct task tokens matched (a file hit by more of the query is a
    stronger anchor). Areas are excluded — they are containers, not answers.
    """
    toks = _task_tokens(task)
    if not toks:
        return {}
    seeds: dict[str, float] = {}
    for n in graph.nodes.values():
        if n.type is NodeType.AREA:
            continue
        hay = n.label.lower() + " " + (n.path or "").lower()
        hits = sum(1 for t in set(toks) if t in hay)
        if hits:
            seeds[n.id] = float(hits)
    return seeds


def _node_token_cost(node: Node) -> int:
    """Rough token cost of a node's compact entry (id+type+path). chars/4 is an estimate."""
    chars = len(node.id) + len(node.type.value) + len(node.path or "") + 12
    return max(1, round(chars / 4))


def focus(
    graph: Graph,
    task: str,
    *,
    budget_tokens: int = 2000,
    damping: float = 0.85,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return the minimal high-value subgraph for a task, within a token budget.

    Anchors the task to seed nodes (name/path match), runs **personalised PageRank** from them,
    and fills a token budget with the highest-scoring nodes (seeds first), plus the knowledge
    edges among the chosen nodes. With no seed match it falls back to global importance, so the
    assistant always gets *something* relevant rather than the whole digest.
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

    ranked = sorted(
        ((nid, s) for nid, s in scores.items()
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
        cost = _node_token_cost(graph.nodes[nid])
        if chosen and spent + cost > budget_tokens:
            break
        chosen.append(nid)
        seen.add(nid)
        spent += cost

    nodes_out = [{"id": nid, "type": graph.nodes[nid].type.value,
                  "path": graph.nodes[nid].path, "score": round(scores[nid], 6),
                  "seed": nid in seed_ids}
                 for nid in chosen]
    edges_out = [{"source": e.source, "target": e.target, "type": e.type.value}
                 for e in graph.edges
                 if e.type in KNOWLEDGE and e.source in seen and e.target in seen]
    return {
        "task": task,
        "seeds": sorted(seeds),
        "fallback": fallback,
        "budget_tokens": budget_tokens,
        "token_estimate": spent,
        "nodes": nodes_out,
        "edges": edges_out,
    }
