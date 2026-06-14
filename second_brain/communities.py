"""Community detection over the project graph (deterministic, zero-dependency).

Communities are the project's *real* modules: clusters discovered from how files actually link
to each other (imports + references), not from the folder layout. Two files in different folders
that constantly reference each other belong to the same community; a folder whose files never link
to each other is not one. This is the lens that turns a flat file list into the project's true,
self-organising structure.

The algorithm is **label propagation** made deterministic: a fixed node order, a stable tie-break
(lowest label wins), in-place (sequential) updates, and a bounded number of passes. Same graph in
-> same labels out, every run. No randomness, no dependencies (stdlib only).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from second_brain.model import EdgeType, Graph, NodeType

# Knowledge edges define "real" relatedness for clustering (not folder membership / git touches).
KNOWLEDGE: tuple[EdgeType, ...] = (EdgeType.IMPORTS, EdgeType.REFERENCES)
_MAX_PASSES = 12


def _area_of(path: str | None) -> str:
    if not path:
        return "(root)"
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def _adjacency(graph: Graph, relations: tuple[EdgeType, ...]) -> dict[str, set[str]]:
    """Undirected adjacency restricted to ``relations`` edges between existing nodes."""
    adj: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        if e.type not in relations:
            continue
        if e.source == e.target:
            continue
        if e.source in graph.nodes and e.target in graph.nodes:
            adj[e.source].add(e.target)
            adj[e.target].add(e.source)
    return adj


def detect(
    graph: Graph,
    *,
    relations: tuple[EdgeType, ...] = KNOWLEDGE,
    max_passes: int = _MAX_PASSES,
) -> dict[str, str]:
    """Assign each file node a community label via deterministic label propagation.

    Returns ``{node_id: community_label}`` for every file-backed node (``path`` set, not an area).
    A node with at least one knowledge edge gets a propagated label; a node with no knowledge edge
    falls back to ``area:<top-folder>`` so isolated files cluster by location instead of scattering.
    Labels are opaque identifiers (a seed node id that "won"); :func:`summarize` renames them to
    stable ordinals for display.
    """
    adj = _adjacency(graph, relations)
    knodes = sorted(adj.keys())  # fixed, stable iteration order -> deterministic
    labels: dict[str, str] = {n: n for n in knodes}  # seed: every node its own label
    for _ in range(max(1, max_passes)):
        changed = False
        for n in knodes:
            tally: dict[str, int] = defaultdict(int)
            for m in adj[n]:
                tally[labels[m]] += 1
            if not tally:
                continue
            # Most frequent neighbour label; ties broken by the lexicographically smallest label.
            best = min(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if best != labels[n]:
                labels[n] = best
                changed = True
        if not changed:
            break

    # Communities describe files/modules only — never areas, recorded decisions, or sessions.
    # We exclude both by missing path (those nodes have none) AND by type, so the guarantee holds
    # even if such a node ever carried a path.
    excluded = (NodeType.AREA, NodeType.DECISION, NodeType.SESSION)
    comm: dict[str, str] = {}
    for nid, node in graph.nodes.items():
        if node.path is None or node.type in excluded:
            continue
        comm[nid] = labels.get(nid, f"area:{_area_of(node.path)}")
    return comm


def _knowledge_degree(graph: Graph, relations: tuple[EdgeType, ...]) -> dict[str, int]:
    """Knowledge degree per node, ignoring self-loops and edges to non-existent nodes."""
    deg: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        if e.type not in relations or e.source == e.target:
            continue
        if e.source in graph.nodes:
            deg[e.source] += 1
        if e.target in graph.nodes:
            deg[e.target] += 1
    return deg


def _ordered_labels(comm: dict[str, str]) -> list[str]:
    """Community labels ordered by size (desc), tie-break by label — stable across runs."""
    sizes: dict[str, int] = defaultdict(int)
    for label in comm.values():
        sizes[label] += 1
    return sorted(sizes.keys(), key=lambda label: (-sizes[label], label))


def names(comm: dict[str, str]) -> dict[str, str]:
    """Map each community label to a stable ordinal name (``Cluster 1`` = largest)."""
    return {label: f"Cluster {i}" for i, label in enumerate(_ordered_labels(comm), start=1)}


def summarize(
    graph: Graph,
    comm: dict[str, str],
    *,
    relations: tuple[EdgeType, ...] = KNOWLEDGE,
    key_files: int = 5,
) -> list[dict[str, Any]]:
    """Summarise each community: name, size, key files, dominant node types, cohesion.

    ``cohesion`` is the share of a community's touching knowledge edges that stay inside it
    (internal / (internal + boundary)); 1.0 = self-contained, lower = leaky. Communities are
    returned largest first, each named ``Cluster N``.
    """
    name_of = names(comm)
    deg = _knowledge_degree(graph, relations)
    members: dict[str, list[str]] = defaultdict(list)
    for nid, label in comm.items():
        members[label].append(nid)

    internal: dict[str, int] = defaultdict(int)
    boundary: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        if e.type not in relations or e.source == e.target:
            continue
        cs, ct = comm.get(e.source), comm.get(e.target)
        if cs is None and ct is None:
            continue
        if cs == ct:
            internal[cs] += 1
        else:
            if cs is not None:
                boundary[cs] += 1
            if ct is not None:
                boundary[ct] += 1

    rows: list[dict[str, Any]] = []
    for label in _ordered_labels(comm):
        ids = members[label]
        types: dict[str, int] = defaultdict(int)
        for nid in ids:
            node = graph.nodes.get(nid)
            if node is not None:
                types[node.type.value] += 1
        dominant = [t for t, _ in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        top = sorted(ids, key=lambda nid: (-deg.get(nid, 0), nid))[:key_files]
        denom = internal[label] + boundary[label]
        cohesion = round(internal[label] / denom, 2) if denom else 0.0
        rows.append({
            "name": name_of[label],
            "label": label,
            "size": len(ids),
            "key_files": top,
            "dominant_types": dominant,
            "cohesion": cohesion,
            "internal_edges": internal[label],
            "boundary_edges": boundary[label],
        })
    return rows


def surprising_edges(
    graph: Graph,
    comm: dict[str, str],
    *,
    relations: tuple[EdgeType, ...] = KNOWLEDGE,
    top: int = 10,
) -> list[dict[str, Any]]:
    """Return the most important *cross-community* knowledge edges (the hidden dependencies).

    Importance is the summed knowledge degree of the two endpoints — an edge between two
    well-connected files in different communities is a more surprising/important bridge than one
    between two leaf nodes. Results are deterministic (sorted by importance, then endpoints).
    """
    name_of = names(comm)
    deg = _knowledge_degree(graph, relations)
    rows: list[dict[str, Any]] = []
    for e in graph.edges:
        if e.type not in relations:
            continue
        cs, ct = comm.get(e.source), comm.get(e.target)
        if cs is None or ct is None or cs == ct:
            continue
        rows.append({
            "source": e.source,
            "target": e.target,
            "type": e.type.value,
            "source_community": name_of.get(cs, cs),
            "target_community": name_of.get(ct, ct),
            "weight": deg.get(e.source, 0) + deg.get(e.target, 0),
        })
    rows.sort(key=lambda r: (-r["weight"], r["source"], r["target"], r["type"]))
    return rows[: max(0, top)]


__all__ = ["KNOWLEDGE", "detect", "names", "summarize", "surprising_edges"]
