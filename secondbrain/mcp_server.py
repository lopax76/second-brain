"""Optional MCP server exposing Second Brain\'s low-token queries to AI assistants.

This is the piece that lets an assistant *query* the project instead of re-reading it. It is
an OPTIONAL extra so the core stays dependency-free:

    pip install second-brain[mcp]
    secondbrain-mcp [PROJECT_PATH]      # defaults to the current directory

Read-only on your sources. Exposes a handful of small, budgeted tools (map / find /
neighbors / subgraph / health) over stdio.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from secondbrain import gate, query, store
from secondbrain.freshness import build_manifest, index
from secondbrain.model import Graph

try:  # pragma: no cover - import-guard
    from mcp.server.fastmcp import FastMCP
except ImportError:
    # Stay importable without the optional extra (linters, autodoc, test collection): keep
    # FastMCP as None and fail with a friendly message only when the server is actually run.
    FastMCP = None

_NO_MCP = "The MCP server needs the optional 'mcp' extra: pip install second-brain[mcp]"


def _graph(project: str) -> Graph:
    return store.load_graph(project) or index(project)[0]


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
    def find(text: str) -> list[dict[str, Any]]:
        """Find files/nodes whose name or path contains ``text`` (case-insensitive)."""
        return query.find(_graph(project), text)

    @server.tool()
    def neighbors(node_id: str) -> dict[str, Any]:
        """A node and its incoming/outgoing connections (imports, references, area membership)."""
        # Distinct error for an unknown node, so an assistant can tell "no edges" from "no node".
        res = query.neighbors(_graph(project), node_id)
        return res if res is not None else {"error": "node not found", "id": node_id}

    @server.tool()
    def subgraph(node_id: str, hops: int = 1) -> dict[str, Any]:
        """A small subgraph (nodes + edges) around ``node_id`` within ``hops``."""
        return query.subgraph(_graph(project), node_id, hops=hops)

    @server.tool()
    def health() -> dict[str, Any]:
        """Anti-drift status: broken references, stale files vs the last build, orphan count."""
        g = store.load_graph(project)
        old = store.load_manifest(project)
        if g is None or old is None:
            return {"status": "no-baseline", "hint": "run 'secondbrain build' first"}
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
