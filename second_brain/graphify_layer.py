"""Read graphify's code graph as Second Brain's code layer (0.10, decision D-SB-7).

graphify (https://github.com/safishamsi/graphify) parses 37 languages with tree-sitter and writes
``graphify-out/graph.json`` (networkx node-link: ``nodes`` with ``source_file``, ``links`` with
``relation`` and ``confidence``). Second Brain stays dependency-free and does not parse those
languages itself: where a project HAS a graphify graph, its cross-file relations become edges of
the project graph, read-only, labelled with their provenance.

Rules:
* only relations BETWEEN two different files that both exist as nodes here (the file level is
  Second Brain's level; graphify's symbol nodes stay in graphify);
* ``calls``, ``imports``, ``implements``, ``inherits``, ``uses`` -> an ``imports`` edge (A uses B),
  ``references`` -> a ``references`` edge; meta ``{"via": "graphify", "relation", "confidence"}``;
* freshness per edge: if either file changed after graphify wrote its graph, the relation may no
  longer be true and is NOT imported (counted as skipped) — a stale map is worse than none.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from second_brain.model import Edge, EdgeType, Graph

_DEPENDS = {"calls", "imports", "implements", "inherits", "uses", "extends", "imports_from"}
_REFERS = {"references"}


def _root_of(out_dir: Path) -> Path:
    """The folder graphify ran on: ``.graphify_root`` when present, else graphify-out's parent."""
    try:
        txt = (out_dir / ".graphify_root").read_text(encoding="utf-8").strip()
        if txt:
            p = (out_dir.parent / txt).resolve() if not os.path.isabs(txt) else Path(txt)
            if p.is_dir():
                return p
    except OSError:
        pass
    return out_dir.parent.resolve()


def _changed_after(root: Path, fid: str, when: float, cache: dict[str, float]) -> bool:
    """Was file ``fid`` modified after ``when`` (graphify's write)? Cached per build."""
    if fid not in cache:
        try:
            cache[fid] = (root / fid).stat().st_mtime
        except OSError:
            cache[fid] = float("inf")
    return cache[fid] > when


def enrich(graph: Graph, project_root: Path, out_dirs: list[str]) -> dict[str, Any]:
    """Add graphify's cross-file relations to ``graph`` (in place). Returns counts per source."""
    report: dict[str, Any] = {}
    for rel_out in out_dirs:
        out = (project_root / rel_out).resolve()
        gfile = out / "graph.json"
        try:
            gmtime = gfile.stat().st_mtime
            data = json.loads(gfile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report[rel_out] = {"error": "graph.json illeggibile"}
            continue
        groot = _root_of(out)
        try:
            prefix = groot.relative_to(project_root).as_posix()
        except ValueError:
            report[rel_out] = {"error": "radice di graphify fuori dal progetto"}
            continue
        prefix = "" if prefix == "." else prefix + "/"
        node_file: dict[str, str] = {}
        for n in data.get("nodes", []):
            sf = n.get("source_file")
            if isinstance(sf, str) and sf:
                node_file[str(n.get("id"))] = prefix + sf.replace("\\", "/").lstrip("./")
        added = stale = outside = 0
        mtimes: dict[str, float] = {}

        for link in data.get("links", data.get("edges", [])):
            rel = str(link.get("relation", ""))
            if rel in _DEPENDS:
                etype = EdgeType.IMPORTS
            elif rel in _REFERS:
                etype = EdgeType.REFERENCES
            else:
                continue
            a = node_file.get(str(link.get("source")))
            b = node_file.get(str(link.get("target")))
            if not a or not b or a == b:
                continue
            if a not in graph.nodes or b not in graph.nodes:
                outside += 1
                continue
            if (_changed_after(project_root, a, gmtime, mtimes)
                    or _changed_after(project_root, b, gmtime, mtimes)):
                stale += 1
                continue
            if graph.add_edge(Edge(a, b, etype, {"via": "graphify", "relation": rel,
                                                 "confidence": link.get("confidence", "")})):
                added += 1
        report[rel_out] = {"edges": added, "stale_skipped": stale, "not_in_graph": outside}
    return report


__all__ = ["enrich"]
