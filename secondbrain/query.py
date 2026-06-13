"""Low-token query layer over the project graph.

The whole point of Second Brain is that an assistant *queries* the graph and gets compact,
budgeted answers — instead of re-reading whole files. Every function here returns a small,
plain-data structure (ids, types, short labels, counts, sizes) — never file contents — so a
session bootstrap or a targeted question costs a few hundred to a couple thousand tokens, not
tens of thousands. Pure functions over a :class:`~secondbrain.model.Graph`; no I/O, no deps.
"""

from __future__ import annotations

from secondbrain.model import Edge, EdgeType, Graph, Node, NodeType

KNOWLEDGE = (EdgeType.IMPORTS, EdgeType.REFERENCES)


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


def project_map(graph: Graph, *, top: int = 8) -> dict:
    """Compact project digest — the cheap thing to load when work starts.

    Returns areas (with file counts, total size, dominant types), type/edge tallies, the
    most-connected files, and orphan/broken counts. Lists are capped by ``top``.
    """
    files = [n for n in graph.nodes.values() if n.path is not None and n.type is not NodeType.AREA]
    areas: dict[str, dict] = {}
    for n in files:
        a = _area_of(n.path)
        e = areas.setdefault(a, {"files": 0, "size": 0, "types": {}})
        e["files"] += 1
        sz = int(n.meta.get("size", 0))
        e["size"] += sz
        e["types"][n.type.value] = e["types"].get(n.type.value, 0) + sz

    def _area_row(name: str, e: dict) -> dict:
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
    return {
        "project": graph.project,
        "files": len(files),
        "areas": len(areas),
        "links": len(graph.edges),
        "size": sum(int(n.meta.get("size", 0)) for n in files),
        "node_types": counts["nodes"],
        "edge_types": counts["edges"],
        "by_area": area_rows,
        "most_connected": most_connected,
        "orphans": orphans,
        "broken_refs": broken,
    }


def find(graph: Graph, query: str, *, limit: int = 25) -> list[dict]:
    """Return file/entity nodes whose label or path contains ``query`` (case-insensitive)."""
    q = query.lower().strip()
    if not q:
        return []
    hits = [n for n in graph.nodes.values()
            if n.type is not NodeType.AREA
            and (q in n.label.lower() or (n.path and q in n.path.lower()))]
    # Sort by id before capping so the returned subset is deterministic, not insertion-order.
    hits.sort(key=lambda n: n.id)
    return [{"id": n.id, "type": n.type.value, "path": n.path} for n in hits[:limit]]


def neighbors(graph: Graph, node_id: str) -> dict | None:
    """Return a node and its incoming/outgoing connections (compact). None if unknown."""
    n = graph.nodes.get(node_id)
    if n is None:
        return None

    def _row(other: str, etype: str) -> dict:
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


def subgraph(graph: Graph, node_id: str, *, hops: int = 1) -> dict:
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
