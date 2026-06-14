#!/usr/bin/env python
"""Build an ANONYMIZED, single-file vis-network viewer of a project's graph.

Reproducible source of the README hero image (``docs/assets/ui-suite.png``): Second Brain's own
viewer on a real, multi-project workspace with every name anonymized. Kept in-repo so it is never
again a mystery where the anonymized view came from.

Pipeline:
  1. read ``<ROOT>/.secondbrain/graph.json``  (run ``second-brain build <ROOT>`` first)
  2. replace every id / label / path / description / area name with neutral tokens, keeping
     node type, file extension, byte size and the link structure intact -- so the layout,
     communities and node sizes match the real graph, only the names are gone
  3. write the anonymized graph to a throwaway root and render it through the project's own
     ``second-brain view`` pipeline (vis-network, auto-backbone, offline single file)
  4. copy the result to ``<OUT>``

Usage:
  python docs/assets/_anon_view.py <ROOT> <OUT_HTML> [PROJECT_NAME]
  python docs/assets/_anon_view.py "C:/Users/robys/Documents" \
         "C:/Users/robys/Documents/.secondbrain/anon.html" "example suite"
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def anonymize(graph: dict, project: str) -> dict:
    """Return a structurally identical graph with all real names replaced by neutral tokens."""
    nodes = sorted(graph.get("nodes", []), key=lambda n: n["id"])
    idmap: dict[str, str] = {}
    out_nodes: list[dict] = []
    file_i = 0
    area_i = 0
    for n in nodes:
        nid = n["id"]
        ntype = n.get("type", "")
        path = n.get("path")
        if ntype == "area" or nid.startswith("area:"):
            area_i += 1
            new_id = f"area:A{area_i}"
            new_label = f"Area {area_i}"
            new_path = None
        else:
            file_i += 1
            ext = os.path.splitext(path)[1] if path else ""
            new_id = f"n{file_i:06d}{ext}"
            new_label = f"{ntype}-{file_i:04d}{ext}"
            # keep path None for path-less nodes (decisions, sessions) so the viewer
            # still groups them as their own communities instead of dropping them
            new_path = new_id if path else None
        idmap[nid] = new_id
        meta: dict = {}
        size = (n.get("meta") or {}).get("size")
        if size:
            meta["size"] = int(size)
        out_nodes.append({
            "id": new_id, "type": ntype, "label": new_label,
            "description": "", "path": new_path, "meta": meta,
        })
    out_edges: list[dict] = []
    for e in graph.get("edges", []):
        s = idmap.get(e["source"])
        t = idmap.get(e["target"])
        if s is None or t is None:
            continue
        out_edges.append({"source": s, "target": t, "type": e.get("type", "references"), "meta": {}})
    return {"project": project, "nodes": out_nodes, "edges": out_edges}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    out = Path(sys.argv[2])
    project = sys.argv[3] if len(sys.argv) > 3 else "example suite"
    src = root / ".secondbrain" / "graph.json"
    if not src.exists():
        print(f"missing {src}; run first: second-brain build \"{root}\"")
        return 1
    graph = json.loads(src.read_text(encoding="utf-8"))
    anon = anonymize(graph, project)

    # Render directly from the anonymized Graph (same path as `second-brain view`:
    # auto-backbone big graphs, then render the vis-network single-file viewer). We do NOT
    # round-trip through a temp dir + the CLI, because `view` would rebuild the graph from the
    # (empty) temp filesystem and render nothing.
    from second_brain import query, viewer
    from second_brain.model import Graph

    g = Graph.from_dict(anon)
    full = len(g.nodes)
    if full > 8000:
        g = query.backbone(g)
        print(f"backbone: rendering {len(g.nodes)} of {full} nodes")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(viewer.render_view(g), encoding="utf-8", newline="\n")
    print(f"wrote {out} ({out.stat().st_size} bytes) | rendered_nodes={len(g.nodes)} of {full}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
