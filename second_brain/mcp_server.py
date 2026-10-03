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
import threading
import time
from typing import Any

from second_brain import gate, lock, query, store
from second_brain import report as _report
from second_brain.freshness import (
    _refresh_ttl,
    build_manifest,
    fast_signature,
    load_or_refresh,
)
from second_brain.model import Graph

MCP_SDK = ""
try:  # pragma: no cover - import-guard
    # mcp >= 2.0 renamed FastMCP to MCPServer (same decorator API). Before 0.9.6 only the old
    # path was tried, so a fresh install (which pulls mcp 2.x) exited claiming the extra was
    # missing although it was installed.
    from mcp.server.mcpserver import MCPServer as FastMCP
    MCP_SDK = "v2"
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
        MCP_SDK = "v1"
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
    _STORED.clear()


def _graph(project: str) -> Graph:
    """Self-refreshing read, cached in-process within the TTL window (zero I/O on a cache hit)."""
    ttl = _refresh_ttl()
    now = time.monotonic()
    cached = _GRAPH_CACHE.get(project)
    if cached is not None and ttl > 0 and (now - cached[0]) < ttl:
        return cached[1]
    from second_brain import freshness as _fr
    if project in _BUILDING or not (store.store_dir(project) / "graph.json").is_file():
        g, problem = _first_build(project)
    else:
        g = load_or_refresh(project)
        problem = _fr.outcome()[0]
    _PROBLEM[project] = problem
    # a graph served despite a problem is not cached: the next call must retry the refresh
    if problem is None:
        _GRAPH_CACHE[project] = (now, g)
    return g


# First builds running in the background: project -> (thread, start time, result box).
_BUILDING: dict[str, tuple[threading.Thread, float, dict[str, Any]]] = {}


def _build_wait() -> float:
    try:
        return max(0.0, float(os.environ.get("SECOND_BRAIN_BUILD_WAIT", "20")))
    except ValueError:
        return 20.0


def _first_build(project: str) -> tuple[Graph, dict[str, Any] | None]:
    """A project with no graph yet: build it in a background thread and wait a little.

    A small project is ready within the wait and the call answers as before. A very large one
    (35 s measured on 33k files) no longer holds the agent inside the call: after
    ``SECOND_BRAIN_BUILD_WAIT`` seconds (default 20) the call returns an error saying the graph is
    being built and to retry; the build goes on, and the next call picks up its result.
    """
    from second_brain import freshness as _fr
    job = _BUILDING.get(project)
    if job is None:
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["graph"] = load_or_refresh(project)
                box["problem"] = _fr.outcome()[0]
            except BaseException as exc:  # noqa: BLE001 - handed to the caller as is
                box["error"] = exc

        th = threading.Thread(target=run, name=f"second-brain-build:{project}", daemon=True)
        job = (th, time.monotonic(), box)
        _BUILDING[project] = job
        th.start()
    th, started, box = job
    th.join(_build_wait())
    if th.is_alive():
        raise RuntimeError(
            f"Second Brain: il grafo di «{os.path.basename(project) or project}» si sta costruendo "
            f"per la prima volta (da {time.monotonic() - started:.0f} s; un progetto molto grande "
            f"richiede circa un minuto). Riprova fra poco; intanto usa progetto='superiore' o la "
            f"ricerca normale.")
    _BUILDING.pop(project, None)
    if "error" in box:
        raise box["error"]
    return box["graph"], box.get("problem")


_STORED: dict[str, tuple[tuple[int, int], Graph]] = {}


def _stored_graph(project: str) -> Graph | None:
    """The graph AS STORED (no refresh: `health` reports on the store, it does not change it),
    parsed again only when graph.json changed on disk (1.6 s per parse on a 127k-node graph)."""
    p = store.store_dir(project) / "graph.json"
    try:
        st = p.stat()
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    hit = _STORED.get(project)
    if hit is not None and hit[0] == key:
        return hit[1]
    g = store.load_graph(project)
    if g is not None:
        _STORED[project] = (key, g)
    return g


# The last freshness problem per project (busy store, failed refresh), surfaced in the answers:
# a stale map the assistant cannot tell is stale is worse than no map.
_PROBLEM: dict[str, dict[str, Any] | None] = {}


def _warn(project: str, res: Any) -> Any:
    """Put the freshness warning INSIDE the result (clients may show only structured content)."""
    problem = _PROBLEM.get(project)
    if problem and isinstance(res, dict):
        res = {"warning": problem["message"], **res}
    return res


_INSTRUCTIONS = (
    "Second Brain: mappa a basso costo di token dei progetti e della memoria generale. "
    "Orientati con project_map o focus prima di cercare a mano; impact prima di modificare. "
    "In uno spazio di lavoro, `progetto` vuoto = il progetto della tua cartella di lavoro, "
    "'superiore' = tutti i progetti, i file generali e le memorie degli agenti. "
    "Prima di modificare un file chiama posso_scrivere: se l'esito e' 'blocco' un altro agente "
    "ci sta lavorando, non scrivere; a fine lavoro chiudi_lavoro."
)


def resolve_target(base: str, progetto: str = "") -> str:
    """The folder whose graph a tool call should use (see :func:`build_server`)."""
    from second_brain import workspace
    ws = workspace.find_workspace(base)
    if ws is None or os.path.realpath(base) != str(ws.root):
        return base  # a single project: one graph, `progetto` is ignored
    key = progetto.strip()
    if key.lower() in ("superiore", "tutto", "workspace", "generale"):
        return str(ws.root)
    if key:
        p = ws.project_by_id(key)
        if p is None:
            raise ValueError(f"progetto «{key}» non trovato; disponibili: "
                             + ", ".join(pr.id for pr in ws.projects))
        return str(p.root)
    here = ws.project_of(os.getcwd())
    return str(here.root) if here is not None else str(ws.root)


def build_server(base: str):
    """Construct the server bound to ``base`` (no I/O until a tool is called).

    ``base`` is a project folder (one graph), or a WORKSPACE root (0.10): then every tool takes
    ``progetto`` — empty = the project of the agent's working folder, ``"superiore"`` = the
    superior graph (all projects, general memory, agents' memories), or a project id/name.
    """
    if FastMCP is None:  # pragma: no cover - exercised only without the extra installed
        raise ImportError(_NO_MCP)
    server = FastMCP("second-brain", instructions=_INSTRUCTIONS)

    def _dove(progetto: str) -> str:
        return resolve_target(base, progetto)

    @server.tool()
    def project_map(progetto: str = "") -> dict[str, Any]:
        """Compact project digest: areas with file counts/sizes/types, type and edge
        tallies, the most-connected files, and orphan/broken counts. Cheap to load first."""
        project = _dove(progetto)
        return _warn(project, query.project_map(_graph(project)))

    @server.tool()
    def find(text: str, limit: int = 100, progetto: str = "") -> dict[str, Any]:
        """Find files/nodes whose name or path contains ``text`` (case-insensitive).

        Returns the true ``total`` count and up to ``limit`` matches, so a family is never
        silently under-counted. Raise ``limit`` (or read the count) to enumerate fully.
        """
        project = _dove(progetto)
        rows = query.find(_graph(project), text)
        cap = len(rows) if limit <= 0 else limit
        return _warn(project, {"total": len(rows), "shown": min(cap, len(rows)),
                               "matches": rows[:cap]})

    @server.tool()
    def neighbors(node_id: str, limit: int = 0, progetto: str = "") -> dict[str, Any]:
        """A node and its incoming/outgoing connections (imports, references, area membership).

        ``limit`` > 0 caps each direction and reports the true totals + a ``truncated`` flag, so a
        god-node with thousands of edges can't flood the context; 0 (default) returns every edge."""
        project = _dove(progetto)
        # Distinct error for an unknown node, so an assistant can tell "no edges" from "no node".
        res = query.neighbors(_graph(project), node_id, limit=limit)
        return res if res is not None else {"error": "node not found", "id": node_id}

    @server.tool()
    def subgraph(node_id: str, hops: int = 1, progetto: str = "") -> dict[str, Any]:
        """A small subgraph (nodes + edges) around ``node_id`` within ``hops``."""
        project = _dove(progetto)
        return _warn(project, query.subgraph(_graph(project), node_id, hops=hops))

    @server.tool()
    def impact(node_id: str, direction: str = "both", max_depth: int = 2,
               budget: int = 0, progetto: str = "") -> dict[str, Any]:
        """Impact radius of a node, grouped by depth.

        ``direction`` in {up, down, both}: ``upstream`` = who depends on ``node_id`` (what breaks
        if you change it), ``downstream`` = what ``node_id`` depends on. ``budget`` > 0 ranks the
        impacted nodes (nearest + most-connected first) and trims to ~that many tokens, so a hub
        with hundreds of dependents returns only its most important ones; 0 = all, by depth.
        """
        project = _dove(progetto)
        return _warn(project, query.impact(_graph(project), node_id, direction=direction,
                                           max_depth=max_depth, budget_tokens=budget))

    @server.tool()
    def impact_diff(direction: str = "both", max_depth: int = 2, budget: int = 0,
                    progetto: str = "") -> dict[str, Any]:
        """Blast radius of the project's UNCOMMITTED working-tree changes: what the current edits
        affect (``upstream`` = who depends on them) and what they depend on (``downstream``).
        Reads ``git status`` (read-only) — the safety check to run before/after editing. ``budget``
        > 0 ranks the impacted nodes and trims to ~that many tokens (0 = all, grouped by depth)."""
        project = _dove(progetto)
        from second_brain import operational
        return query.impact_diff(_graph(project), operational.working_changes(project),
                                 direction=direction, max_depth=max_depth, budget_tokens=budget)

    @server.tool()
    def why(source: str, target: str, progetto: str = "") -> dict[str, Any]:
        """Shortest path between two nodes (how are they connected?), over the knowledge edges
        (imports/references), undirected. Returns the path node-by-node with the edge types."""
        project = _dove(progetto)
        return _warn(project, query.why(_graph(project), source, target))

    @server.tool()
    def focus(task: str, budget: int = 2000, signatures: bool = False,
              recency: float = 0.0, half_life_days: float = 30.0,
              progetto: str = "") -> dict[str, Any]:
        """Task-aware retrieval: the minimal high-value subgraph for ``task``, within ~``budget``
        tokens. Anchors the task (BM25 lexical ranking) to matching files, runs personalised
        PageRank from them, and returns the top nodes + the knowledge edges among them — the
        context for a task, not the whole digest. ``signatures=True`` also returns the key symbol
        signatures of the top Python files (the API, without opening them). ``recency`` (0..1,
        default 0) blends a deterministic git recency/frequency signal into the ranking so
        recently/often-touched files surface first (the ACT-R base-level of memory);
        ``half_life_days`` sets the decay (default 30); falls back to global importance."""
        project = _dove(progetto)
        g = _graph(project)
        res = query.focus(g, task, budget_tokens=budget,
                          recency=recency, half_life_days=half_life_days)
        if signatures:
            query.attach_signatures(g, project, res)
        return _warn(project, res)

    @server.tool()
    def report(max_chars: int = 6000, progetto: str = "") -> str:
        """GRAPH_REPORT.md (god nodes, communities, surprising links, decisions, problems) as
        Markdown, cut at ``max_chars`` (default 6000, about 1.5k tokens; 0 = whole report). On a
        large tree the whole report is tens of thousands of tokens: prefer project_map/focus."""
        project = _dove(progetto)
        text = _report.render_report(_graph(project), root=project)
        if max_chars > 0 and len(text) > max_chars:
            cut = text.rfind("\n", 0, max_chars)
            text = (text[: cut if cut > 0 else max_chars]
                    + f"\n\n… report troncato a {max_chars} di {len(text)} caratteri: "
                      "usa focus/communities per le parti che servono, o max_chars=0.")
        problem = _PROBLEM.get(project)
        return f"> ATTENZIONE: {problem['message']}\n\n{text}" if problem else text

    @server.tool()
    def communities(key_files: int = 5, surprising: int = 10, limit: int = 0,
                    progetto: str = "") -> dict[str, Any]:
        """The project's real modules: clusters from imports+references (not folders), each with
        size, cohesion, key files and dominant types, plus the top cross-module bridges. The
        structural lens, far cheaper than loading the full report. ``limit`` > 0 returns only the
        N largest communities (with the true total + ``truncated``); 0 (default) returns all."""
        project = _dove(progetto)
        return query.community_summary(_graph(project), key_files=key_files,
                                       surprising=surprising, limit=limit)

    @server.tool()
    def health(deep: bool = False, progetto: str = "") -> dict[str, Any]:
        """Anti-drift status: broken references, files changed since the last build, orphans.

        Default: the cheap stat check (size+mtime per file, no file read). ``deep=True`` re-hashes
        every file by content, like ``second-brain gate`` (slow on a large tree: 66 s measured on
        a 400k-file workspace)."""
        project = _dove(progetto)
        g = _stored_graph(project)
        if g is None:
            return {"status": "no-baseline", "hint": "run 'second-brain build' first"}
        holder = lock.read_holder(store.store_dir(project))
        if deep:
            old = store.load_manifest(project)
            if old is None:
                return {"status": "no-baseline", "hint": "run 'second-brain build' first"}
            rep = gate.evaluate(g, old, build_manifest(project))
            out = {"ok": rep.ok, "check": "content", "broken": rep.broken, "stale": rep.stale,
                   "orphans": len(rep.orphans)}
        else:
            old_sig = store.load_signature(project) or {}
            new_sig = fast_signature(project, confirm=old_sig)
            changed = sorted(r for r in old_sig.keys() & new_sig.keys() if old_sig[r] != new_sig[r])
            stale = {"added": sorted(new_sig.keys() - old_sig.keys()),
                     "removed": sorted(old_sig.keys() - new_sig.keys()), "changed": changed}
            broken = gate.find_broken(g)
            out = {"ok": not broken and not any(stale.values()), "check": "stat",
                   "broken": broken, "stale": {k: v[:50] for k, v in stale.items()},
                   "stale_counts": {k: len(v) for k, v in stale.items()},
                   "orphans": len(gate.find_orphans(g))}
        if holder:
            out["rebuilding"] = holder
        return _warn(project, out)

    # --- anti-collisione fra agenti (0.10) -------------------------------------------------
    from second_brain import lavori
    from second_brain.lock import agent_name

    def _file(path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)

    @server.tool()
    def posso_scrivere(file: str) -> dict[str, Any]:
        """Call BEFORE modifying a file. esito: ok | attenzione (linked to another agent's work,
        or changed on disk since your last write: re-read it) | blocco (another agent is working
        on this file: do NOT write it). On ok/attenzione the file is recorded as yours."""
        return lavori.posso_scrivere(_file(file), agent_name())

    @server.tool()
    def inizia_lavoro(intento: str, file: list[str] | None = None,
                      progetto: str = "") -> dict[str, Any]:
        """Declare your work on a project (intent + files you plan to change), so other agents
        are stopped before touching them. Returns who else is working there."""
        return lavori.inizia(_dove(progetto), agent_name(), intento=intento, file=file or [])

    @server.tool()
    def chiudi_lavoro(progetto: str = "") -> dict[str, Any]:
        """End your work on the project: frees your files for the other agents."""
        return lavori.chiudi(_dove(progetto), agent_name())

    @server.tool()
    def lavori_in_corso() -> dict[str, Any]:
        """Every active work in the workspace: project, agent, intent, files, last sign of life."""
        return {"lavori": lavori.in_corso(base)}

    return server


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--workspace":  # same as passing the workspace folder
        args = args[1:]
    project = args[0] if args else os.getcwd()
    if FastMCP is None:
        print(_NO_MCP, file=sys.stderr)
        return 2
    build_server(project).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
