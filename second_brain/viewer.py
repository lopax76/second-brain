"""Render a single-file, offline graph viewer (vis-network) with data + library inlined.

The viewer is a self-contained HTML file: the graph data and the rendering library are both
embedded, so it opens straight from disk with no local server, no CORS, and no sibling files to
lose — just double-click ``.secondbrain/view.html``. Fully offline: no CDN, no network.

The interactive viewer (force-directed layout, community colouring, search, click-to-inspect
panel with neighbour navigation, and per-community show/hide filters) is adapted from **Graphify**
(https://github.com/safishamsi/graphify, MIT License, Copyright (c) 2026 Safi Shamsi). It renders
with **vis-network** (Apache-2.0 OR MIT). Both are bundled offline; see THIRD_PARTY_NOTICES.md.
With thanks to the Graphify project.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from second_brain import communities
from second_brain.model import NODE_COLORS, EdgeType, Graph, NodeType
from second_brain.store import store_dir

_UI_DIR = Path(__file__).parent / "ui"
_TEMPLATE = _UI_DIR / "template.html"
_LIB = _UI_DIR / "vis-bundle.min.js"
_LIB_TAG = '<script src="vis-bundle.min.js"></script>'
_TOKEN = "__SB_DATA__"

_KNOWLEDGE = (EdgeType.IMPORTS, EdgeType.REFERENCES)

# Categorical palette for communities (from Graphify, MIT — Tableau 10).
COMMUNITY_COLORS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
]

_TYPE_COMMUNITY_NAMES = {"decision": "Decisions", "session": "Sessions"}


def _build_payload(graph: Graph) -> dict:
    """Shape the graph into vis-network nodes/edges/legend (the Graphify viewer's data model).

    Area nodes and ``belongs_to`` edges are dropped: those star-hubs would collapse the layout
    into a hairball and carry no community signal. Communities come from
    :mod:`second_brain.communities` (files); decision/session nodes form their own groups.
    """
    rendered = [n for n in graph.nodes.values() if n.type is not NodeType.AREA]
    rid = {n.id for n in rendered}
    comm = communities.detect(graph)
    cnames = communities.names(comm)

    def clabel(node) -> str:
        return comm.get(node.id) or f"__type__:{node.type.value}"

    def cname(label: str) -> str:
        if label in cnames:
            return cnames[label]
        if label.startswith("__type__:"):
            t = label.split(":", 1)[1]
            return _TYPE_COMMUNITY_NAMES.get(t, t.capitalize())
        return label

    redges = [e for e in graph.edges
              if e.type is not EdgeType.BELONGS_TO and e.source in rid and e.target in rid]
    deg: dict[str, int] = defaultdict(int)
    for e in redges:
        deg[e.source] += 1
        deg[e.target] += 1
    max_deg = max(deg.values(), default=1) or 1

    members: dict[str, int] = defaultdict(int)
    for n in rendered:
        members[clabel(n)] += 1
    ordered = sorted(members, key=lambda lbl: (-members[lbl], lbl))
    cid_of = {lbl: i for i, lbl in enumerate(ordered)}

    vis_nodes = []
    for n in rendered:
        lbl = clabel(n)
        cid = cid_of[lbl]
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        d = deg.get(n.id, 0)
        vis_nodes.append({
            "id": n.id,
            "label": n.label,
            "color": {"background": color, "border": color,
                      "highlight": {"background": "#ffffff", "border": color}},
            "size": round(10 + 30 * (d / max_deg), 1),
            # only label hubs by default; smaller nodes reveal their label on hover/click
            "font": {"size": 12 if d >= max_deg * 0.15 else 0, "color": "#ffffff"},
            "title": n.path or n.label,
            "community": cid,
            "community_name": cname(lbl),
            "source_file": n.path or "",
            "file_type": n.type.value,
            "degree": d,
            # richer file info for the inspect panel (does not affect the graph rendering)
            "bytes": int(n.meta.get("size", 0) or 0),
            "description": n.description or "",
            "broken": list(n.meta.get("broken_refs", []) or []),
        })

    vis_edges = []
    for e in redges:
        kn = e.type in _KNOWLEDGE
        vis_edges.append({
            "from": e.source, "to": e.target, "title": e.type.value,
            "dashes": not kn, "width": 2 if kn else 1,
            "color": {"opacity": 0.7 if kn else 0.35},
        })

    legend = [{"cid": cid_of[lbl], "color": COMMUNITY_COLORS[cid_of[lbl] % len(COMMUNITY_COLORS)],
               "label": cname(lbl), "count": members[lbl]} for lbl in ordered]

    # Overview ("general info"): per file-type count + total size, over all file nodes.
    type_colors = {k.value: v for k, v in NODE_COLORS.items()}
    type_stat: dict[str, dict[str, int]] = {}
    for n in graph.nodes.values():
        if n.path is None:
            continue
        e = type_stat.setdefault(n.type.value, {"count": 0, "bytes": 0})
        e["count"] += 1
        e["bytes"] += int(n.meta.get("size", 0) or 0)
    types = [{"type": t, "count": v["count"], "bytes": v["bytes"],
              "color": type_colors.get(t, "#888888")}
             for t, v in sorted(type_stat.items(), key=lambda kv: (-kv[1]["count"], kv[0]))]

    return {
        "project": graph.project,
        "nodes": vis_nodes,
        "edges": vis_edges,
        "legend": legend,
        "types": types,
        "totals": {"files": sum(v["count"] for v in type_stat.values()),
                   "bytes": sum(v["bytes"] for v in type_stat.values())},
        "stats": {"nodes": len(vis_nodes), "edges": len(vis_edges), "communities": len(ordered)},
    }


def render_view(graph: Graph) -> str:
    """Return a standalone, single-file HTML document for ``graph`` (vis-network, offline)."""
    payload = json.dumps(_build_payload(graph), ensure_ascii=False).replace("<", "\\u003c")
    # The payload lives in a non-executable <script type="application/json"> block; escaping every
    # "<" as < means no "</script>" can break out of it. JSON.parse decodes it back.
    try:
        template = _TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"viewer template not found at {_TEMPLATE} - the package may be installed without "
            "its UI data files; reinstall second-brain"
        ) from exc
    try:
        lib = _LIB.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"viewer library not found at {_LIB} - the package may be installed without "
            "its UI data files; reinstall second-brain"
        ) from exc
    html = template.replace(_TOKEN, payload)
    lib_inline = lib.replace("</script", "<\\/script")
    return html.replace(_LIB_TAG, f"<script>\n{lib_inline}\n</script>")


def write_view(root: str | os.PathLike[str], graph: Graph) -> Path:
    """Write the single-file viewer to ``<root>/.secondbrain/view.html``; return its path."""
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "view.html"
    out.write_text(render_view(graph), encoding="utf-8", newline="\n")
    return out
