"""Optional MCP server exposing Second Brain\'s low-token queries to AI assistants.

This is the piece that lets an assistant *query* the project instead of re-reading it. It is
an OPTIONAL extra so the core stays dependency-free:

    pip install "second-brain-graph[mcp]"
    second-brain-mcp [PROJECT_PATH]      # defaults to the current directory

Read-only on your sources. Exposes small, budgeted tools (project_map / find / neighbors /
subgraph / impact / impact_diff / why / communities / focus / report / health) over stdio.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from second_brain import gate, query, store
from second_brain import report as _report
from second_brain.freshness import _refresh_ttl, build_manifest, load_or_refresh
from second_brain.model import Graph

try:  # pragma: no cover - import-guard
    from mcp.server.fastmcp import FastMCP
except ImportError:
    # Stay importable without the optional extra (linters, autodoc, test collection): keep
    # FastMCP as None and fail with a friendly message only when the server is actually run.
    FastMCP = None

_NO_MCP = 'The MCP server needs the optional "mcp" extra: pip install "second-brain-graph[mcp]"'


# In-process graph cache for the long-running MCP server. A tool call reuses the loaded graph
# within the freshness TTL window (SECOND_BRAIN_REFRESH_TTL, default 150s) instead of re-parsing
# graph.json and re-stat'ing every file on each call — the difference between ~16s and instant on
# a 100k-file repo. Outside the window, load_or_refresh re-checks the content signature and
# reloads/rebuilds if the project changed. One project per server, so a tiny dict suffices.
_GRAPH_CACHE: dict[str, tuple[float, Graph]] = {}


def clear_graph_cache() -> None:
    """Drop the in-process graph cache (e.g. after an out-of-band rebuild)."""
    _GRAPH_CACHE.clear()


def _graph(project: str) -> Graph:
    """Self-refreshing read, cached in-process within the TTL window (zero I/O on a cache hit)."""
    ttl = _refresh_ttl()
    now = time.monotonic()
    cached = _GRAPH_CACHE.get(project)
    if cached is not None and ttl > 0 and (now - cached[0]) < ttl:
        return cached[1]
    g = load_or_refresh(project)
    _GRAPH_CACHE[project] = (now, g)
    return g


def build_server(project: str):
    """Construct the FastMCP server bound to ``project`` (no I/O until a tool is called)."""
    if FastMCP is None:  # pragma: no cover - exercised only without the extra installed
        raise ImportError(_NO_MCP)
    server = FastMCP("second-brain")

    @server.tool()
    def project_map() -> dict[str, Any]:
        """Compact project digest: areas with file counts/sizes/types, type and edge
        tallies, the most-connected files, and orphan/broken counts. Cheap to load first."""
        return query.project_map(_graph(project))

    @server.tool()
    def find(text: str, limit: int = 100) -> dict[str, Any]:
        """Find files/nodes whose name or path contains ``text`` (case-insensitive).

        Returns the true ``total`` count and up to ``limit`` matches, so a family is never
        silently under-counted. Raise ``limit`` (or read the count) to enumerate fully.
        """
        rows = query.find(_graph(project), text)
        cap = len(rows) if limit <= 0 else limit
        return {"total": len(rows), "shown": min(cap, len(rows)), "matches": rows[:cap]}

    @server.tool()
    def neighbors(node_id: str, limit: int = 0) -> dict[str, Any]:
        """A node and its incoming/outgoing connections (imports, references, area membership).

        ``limit`` > 0 caps each direction and reports the true totals + a ``truncated`` flag, so a
        god-node with thousands of edges can't flood the context; 0 (default) returns every edge."""
        # Distinct error for an unknown node, so an assistant can tell "no edges" from "no node".
        res = query.neighbors(_graph(project), node_id, limit=limit)
        return res if res is not None else {"error": "node not found", "id": node_id}

    @server.tool()
    def subgraph(node_id: str, hops: int = 1) -> dict[str, Any]:
        """A small subgraph (nodes + edges) around ``node_id`` within ``hops``."""
        return query.subgraph(_graph(project), node_id, hops=hops)

    @server.tool()
    def impact(node_id: str, direction: str = "both", max_depth: int = 2,
               budget: int = 0) -> dict[str, Any]:
        """Impact radius of a node, grouped by depth.

        ``direction`` in {up, down, both}: ``upstream`` = who depends on ``node_id`` (what breaks
        if you change it), ``downstream`` = what ``node_id`` depends on. ``budget`` > 0 ranks the
        impacted nodes (nearest + most-connected first) and trims to ~that many tokens, so a hub
        with hundreds of dependents returns only its most important ones; 0 = all, by depth.
        """
        return query.impact(_graph(project), node_id, direction=direction,
                            max_depth=max_depth, budget_tokens=budget)

    @server.tool()
    def impact_diff(direction: str = "both", max_depth: int = 2, budget: int = 0) -> dict[str, Any]:
        """Blast radius of the project's UNCOMMITTED working-tree changes: what the current edits
        affect (``upstream`` = who depends on them) and what they depend on (``downstream``).
        Reads ``git status`` (read-only) — the safety check to run before/after editing. ``budget``
        > 0 ranks the impacted nodes and trims to ~that many tokens (0 = all, grouped by depth)."""
        from second_brain import operational
        return query.impact_diff(_graph(project), operational.working_changes(project),
                                 direction=direction, max_depth=max_depth, budget_tokens=budget)

    @server.tool()
    def why(source: str, target: str) -> dict[str, Any]:
        """Shortest path between two nodes (how are they connected?), over the knowledge edges
        (imports/references), undirected. Returns the path node-by-node with the edge types."""
        return query.why(_graph(project), source, target)

    @server.tool()
    def focus(task: str, budget: int = 2000, signatures: bool = False,
              recency: float = 0.0, half_life_days: float = 30.0) -> dict[str, Any]:
        """Task-aware retrieval: the minimal high-value subgraph for ``task``, within ~``budget``
        tokens. Anchors the task (BM25 lexical ranking) to matching files, runs personalised
        PageRank from them, and returns the top nodes + the knowledge edges among them — the
        context for a task, not the whole digest. ``signatures=True`` also returns the key symbol
        signatures of the top Python files (the API, without opening them). ``recency`` (0..1,
        default 0) blends a deterministic git recency/frequency signal into the ranking so
        recently/often-touched files surface first (the ACT-R base-level of memory);
        ``half_life_days`` sets the decay (default 30); falls back to global importance."""
        g = _graph(project)
        res = query.focus(g, task, budget_tokens=budget,
                          recency=recency, half_life_days=half_life_days)
        if signatures:
            query.attach_signatures(g, project, res)
        return res

    @server.tool()
    def report() -> str:
        """The full GRAPH_REPORT.md (god nodes, communities, surprising links, decisions,
        problems) as Markdown — the cheapest way to orient before grepping the project."""
        return _report.render_report(_graph(project), root=project)

    @server.tool()
    def communities(key_files: int = 5, surprising: int = 10, limit: int = 0) -> dict[str, Any]:
        """The project's real modules: clusters from imports+references (not folders), each with
        size, cohesion, key files and dominant types, plus the top cross-module bridges. The
        structural lens, far cheaper than loading the full report. ``limit`` > 0 returns only the
        N largest communities (with the true total + ``truncated``); 0 (default) returns all."""
        return query.community_summary(_graph(project), key_files=key_files,
                                       surprising=surprising, limit=limit)

    @server.tool()
    def health() -> dict[str, Any]:
        """Anti-drift status: broken references, stale files vs the last build, orphan count."""
        g = store.load_graph(project)
        old = store.load_manifest(project)
        if g is None or old is None:
            return {"status": "no-baseline", "hint": "run 'second-brain build' first"}
        rep = gate.evaluate(g, old, build_manifest(project))
        return {"ok": rep.ok, "broken": rep.broken, "stale": rep.stale,
                "orphans": len(rep.orphans)}

    return server


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    project = args[0] if args else os.getcwd()
    if FastMCP is None:
        print(_NO_MCP, file=sys.stderr)
        return 2
    build_server(project).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
