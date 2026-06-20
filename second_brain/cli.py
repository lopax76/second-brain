"""Command-line interface: build, gate, view, stats, and the query commands.

Read-only on your sources: every command only reads the project and writes derived files
under ``.secondbrain/``.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from second_brain import __version__, agent_integration, assess, gate, query, report, store
from second_brain.freshness import build_manifest, fast_signature, index, load_or_refresh
from second_brain.model import Graph
from second_brain.viewer import write_view


def _human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _build(path: str, *, symbols: bool = False) -> tuple[Graph, dict[str, str]]:
    # Single filesystem walk produces both the graph and the manifest.
    return index(path, symbols=symbols)


def _load_or_build(path: str) -> Graph:
    # Self-refreshing: auto-builds on first touch and rebuilds only if the project changed
    # (stat-only staleness check), so queries never answer from a stale map. Disable with
    # SECOND_BRAIN_AUTO_REFRESH=0.
    return load_or_refresh(path)


def cmd_build(args: argparse.Namespace) -> int:
    sym = getattr(args, "symbols", False)
    g, m = _build(args.path, symbols=sym)
    store.save(args.path, g, m, signature=fast_signature(args.path), symbols=sym)
    # scan=False: keep build light (no second per-file integrity scan); `report`/`assess` do it.
    rp = report.write_report(args.path, g, scan=False)
    c = g.counts()
    print(f"built '{g.project}': {len(g.nodes)} nodes, {len(g.edges)} edges")
    print("  nodes:", c["nodes"])
    print("  edges:", c["edges"])
    print(f"  store: {store.store_dir(args.path)}")
    print(f"  report: {rp}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    g = store.load_graph(args.path)
    old = store.load_manifest(args.path)
    if g is None or old is None:
        print("no graph found \u2014 run 'second-brain build' first", file=sys.stderr)
        return 2
    rep = gate.evaluate(g, old, build_manifest(args.path))
    print(rep.summary())
    msg = "OK: fresh and clean" if rep.ok else "DRIFT: rebuild and/or fix the issues above"
    print(msg)
    return 0 if rep.ok else 1


_BACKBONE_AUTO = 8000  # graphs bigger than this auto-render as a backbone to stay light


def cmd_view(args: argparse.Namespace) -> int:
    g, _ = _build(args.path)
    full = len(g.nodes)
    if args.backbone or full > _BACKBONE_AUTO:
        g = query.backbone(g)
        print(f"backbone: rendering {len(g.nodes)} of {full} nodes "
              "(isolated data files summarized on their area)")
    out = write_view(args.path, g)
    print(f"view written: {out}")
    print("open it in a browser (double-click).")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    g, _ = _build(args.path)
    c = g.counts()
    print(f"'{g.project}': {len(g.nodes)} nodes, {len(g.edges)} edges")
    for k, v in sorted(c["nodes"].items()):
        print(f"  {k:10} {v}")
    for k, v in sorted(c["edges"].items()):
        print(f"  -{k:9} {v}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    m = query.project_map(_load_or_build(args.path))
    print(f"{m['project']}: {m['files']} files \u00b7 {m['areas']} areas \u00b7 "
          f"{m['links']} links \u00b7 {_human(m['size'])}")
    print("by area:")
    for a in m["by_area"]:
        tt = ", ".join(a["top_types"])
        print(f"  {a['area']:16} {a['files']:4} files  {_human(a['size']):>9}  [{tt}]")
    print("most connected:")
    for x in m["most_connected"]:
        print(f"  {x['degree']:3}  {x['id']}  ({x['type']})")
    print(f"orphans: {m['orphans']} \u00b7 broken refs: {m['broken_refs']}")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    res = query.find(_load_or_build(args.path), args.query)
    cap = len(res) if args.all else max(0, args.limit)
    for r in res[:cap]:
        print(f"  {r['type']:9} {r['id']}")
    if cap < len(res):
        print(f"({len(res)} matches — showing {cap}; use --all or --limit N)")
    else:
        print(f"({len(res)} matches)")
    return 0


def cmd_neighbors(args: argparse.Namespace) -> int:
    n = query.neighbors(_load_or_build(args.path), args.node, limit=args.limit)
    if n is None:
        print(f"node not found: {args.node}", file=sys.stderr)
        return 1
    print(f"{n['id']} ({n['type']}) \u00b7 {_human(n['size'])}")
    if n["description"]:
        print(f"  {n['description']}")
    if n["broken_refs"]:
        print(f"  broken refs: {n['broken_refs']}")
    print(f"  outgoing ({len(n['outgoing'])}/{n['outgoing_total']}):")
    for o in n["outgoing"]:
        print(f"    -{o['edge']}-> {o['id']} ({o['type']})")
    print(f"  incoming ({len(n['incoming'])}/{n['incoming_total']}):")
    for o in n["incoming"]:
        print(f"    <-{o['edge']}- {o['id']} ({o['type']})")
    if n["truncated"]:
        print("  (truncated \u2014 raise --limit, or 0 for all)")
    return 0


def _emit_impact(title: str, groups: dict, truncated: bool,
                 empty_hint: str | None = None) -> None:
    print(f"{title}:")
    if not groups:
        print(f"  (none - {empty_hint})" if empty_hint else "  (none)")
        return
    for depth in sorted(groups):
        for r in groups[depth]:
            print(f"  d{depth}  -{r['edge']}- {r['id']} ({r['type']})")
    if truncated:
        print("  ...(capped)")


def cmd_impact(args: argparse.Namespace) -> int:
    direction = "up" if args.up else ("down" if args.down else "both")

    if getattr(args, "diff", False):
        from second_brain import operational
        root = args.node or "."  # with --diff the optional positional is the project path
        res = query.impact_diff(_load_or_build(root), operational.working_changes(root),
                                direction=direction, max_depth=args.depth)
        print(f"working-tree changes: {len(res['changed'])} file(s) — "
              f"{len(res['seeds'])} in graph, {len(res['unindexed'])} unindexed")
        for c in res["seeds"]:
            print(f"  * {c}")
        if res["unindexed"]:
            tail = " …" if len(res["unindexed"]) > 10 else ""
            print(f"  (unindexed: {', '.join(res['unindexed'][:10])}{tail})")
        hint = ("every impacted node is already among your changed files"
                if res["seeds"] else None)
        if "upstream" in res:
            _emit_impact("affected — depends on the changes",
                         res["upstream"], res["upstream_truncated"], hint)
        if "downstream" in res:
            _emit_impact("the changes depend on",
                         res["downstream"], res["downstream_truncated"], hint)
        return 0

    if not args.node:
        print("impact: give a node id, or use --diff for the working-tree changes", file=sys.stderr)
        return 2
    res = query.impact(_load_or_build(args.path), args.node,
                       direction=direction, max_depth=args.depth)
    if not res.get("exists"):
        print(f"node not found: {args.node}", file=sys.stderr)
        return 1
    print(f"{res['id']} ({res['type']})")
    if "upstream" in res:
        _emit_impact("upstream (who depends on this)",
                     res["upstream"], res.get("upstream_truncated", False))
    if "downstream" in res:
        _emit_impact("downstream (what this depends on)",
                     res["downstream"], res.get("downstream_truncated", False))
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    res = query.why(_load_or_build(args.path), args.source, args.target)
    if not res.get("exists"):
        print(f"node not found: one or both of {args.source!r}, {args.target!r}", file=sys.stderr)
        return 1
    if not res.get("connected"):
        print(f"no path between {args.source} and {args.target} (within knowledge links)")
        return 0
    print(f"{args.source}  ->  {args.target}   ({res['length']} hops)")
    edges = res["edges"]
    for i, node in enumerate(res["path"]):
        print(f"  {node['id']} ({node['type']})")
        if i < len(edges):
            print(f"    -{edges[i]['type']}->")
    return 0


def cmd_focus(args: argparse.Namespace) -> int:
    res = query.focus(_load_or_build(args.path), args.task, budget_tokens=args.budget)
    if res["fallback"]:
        print(f"focus '{args.task}': no name/path match — showing globally important nodes "
              f"(~{res['token_estimate']} tokens / budget {args.budget})")
    else:
        print(f"focus '{args.task}': {len(res['seeds'])} seed(s), {len(res['nodes'])} nodes, "
              f"~{res['token_estimate']} tokens / budget {args.budget}")
    for x in res["nodes"]:
        mark = "*" if x["seed"] else " "
        print(f" {mark}{x['score']:.3f}  {x['type']:9} {x['id']}")
    if not res["nodes"]:
        print("  (no nodes)")
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    r = assess.assess(args.path)
    out = store.store_dir(args.path)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "assessment.md"
    p.write_text(assess.render_markdown(r), encoding="utf-8", newline="\n")
    print(f"{r['project']}: {r['files']} files, {r['areas']} areas, {r['links']} links")
    print(f"  hidden: {r['truncated']} truncated, {r['empty']} empty, "
          f"{r['orphans']} orphans (~{r['orphans_pct']}%), {r['broken_refs']} broken, "
          f"{r['decisions']} decisions")
    print(f"  orient an assistant: ~{r['tokens_read_all_files']} tokens to read all files "
          f"(~{r['tokens_read_all_docs']} for docs) -> ~{r['tokens_digest']} with SB")
    print(f"  report: {p}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    g = _load_or_build(args.path)
    out = report.write_report(args.path, g)
    m = query.project_map(g)
    print(f"{m['project']}: {m['files']} files, {m['communities']} communities, "
          f"{m['node_types'].get('decision', 0)} decisions, "
          f"{m['orphans']} orphans, {m['broken_refs']} broken refs")
    print(f"report written: {out}")
    return 0


def cmd_communities(args: argparse.Namespace) -> int:
    res = query.community_summary(_load_or_build(args.path), limit=args.limit)
    head = f"{res['count']} communities"
    if res.get("truncated"):
        head += f" (showing {res['shown']})"
    print(head)
    for c in res["communities"]:
        kf = ", ".join(c["key_files"][:3])
        print(f"  {c['name']:10} {c['size']:4} files  cohesion {c['cohesion']:.2f}  [{kf}]")
    if res["surprising_edges"]:
        print("surprising links (cross-module):")
        for e in res["surprising_edges"][:5]:
            print(f"  {e['source']} -{e['type']}- {e['target']}  "
                  f"({e['source_community']} -> {e['target_community']})")
    return 0

def cmd_export(args: argparse.Namespace) -> int:
    from pathlib import Path

    from second_brain.export import to_graphml

    g = _load_or_build(args.path)
    text = to_graphml(g)  # only 'graphml' supported for now (argparse choices)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"exported {len(g.nodes)} nodes, {len(g.edges)} edges -> {args.out}")
    else:
        print(text)
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    if args.action == "install":
        ctx = agent_integration.write_context_files(args.path)
        hook = agent_integration.install_claude_hook(args.path)
    else:
        ctx = agent_integration.remove_context_files(args.path)
        hook = agent_integration.uninstall_claude_hook(args.path)
    for name, act in ctx.items():
        print(f"  {name}: {act}")
    print(f"  .claude/settings.json (PreToolUse hook): {hook}")
    if args.action == "install":
        print("  note: the Claude Code PreToolUse hook injects context only on "
              "Claude Code >= 2.1.9.")
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    if args.action == "install":
        res = agent_integration.install_git_hook(args.path)
    else:
        res = agent_integration.uninstall_git_hook(args.path)
    if "error" in res:
        print(res["error"], file=sys.stderr)
        return 1
    for name, act in res.items():
        print(f"  .git/hooks/{name}: {act}")
    if args.action == "install" and shutil.which("second-brain") is None:
        print("  note: 'second-brain' is not on PATH; the git hook can't run until it is "
              "(activate the project venv, or install second-brain-graph globally).",
              file=sys.stderr)
    return 0


def cmd_hook_context(args: argparse.Namespace) -> int:
    out = agent_integration.hook_context(args.path)
    if out:
        print(out)
    return 0


def cmd_symbols(args: argparse.Namespace) -> int:
    from pathlib import Path

    from second_brain.symbols import extract_symbols, render

    # The file is resolved under the optional project root (default '.'), so symbols is
    # consistent with the other commands: `symbols <file> [path]`.
    p = Path(args.path) / args.file
    if not p.is_file():
        print(f"not a file: {p}", file=sys.stderr)
        return 2
    if p.suffix.lower() != ".py":
        print(f"symbols: Python (.py) files only for now (got '{p.suffix}')", file=sys.stderr)
        return 2
    syms = extract_symbols(p.read_text(encoding="utf-8", errors="ignore"))
    print(render(args.file, syms))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="second-brain",
        description="Second Brain \u2014 a living, low-token map of a project.",
    )
    parser.add_argument("--version", action="version", version=f"second-brain {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("build", help="index the project -> .secondbrain/graph.json")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--symbols", action="store_true",
                    help="also index the Python symbol layer (function/class nodes + calls)")
    sp.set_defaults(func=cmd_build)

    for name, fn, help_text in [
        ("gate", cmd_gate, "anti-drift check (broken refs, stale files, orphans)"),
        ("stats", cmd_stats, "quick counts by node/edge type"),
        ("map", cmd_map, "compact project digest (areas, sizes, most connected)"),
        ("assess", cmd_assess, "one-shot before/after report: problems + token savings"),
        ("report", cmd_report, "write GRAPH_REPORT.md: god nodes, communities, decisions"),
    ]:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("view",
                        help="write a self-contained 2D community-map viewer -> view.html")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--backbone", action="store_true",
                    help="render only areas + knowledge-connected files (auto for huge graphs)")
    sp.set_defaults(func=cmd_view)

    sp = sub.add_parser("communities",
                        help="the project's real modules (clusters) + cross-module bridges")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--limit", type=int, default=0,
                    help="show only the N largest communities (0 = all); the true total is printed")
    sp.set_defaults(func=cmd_communities)

    sp = sub.add_parser("find", help="find nodes by name or path substring")
    sp.add_argument("query", help="substring to search for")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--limit", type=int, default=50,
                    help="max rows to display (default: 50); the true total is always printed")
    sp.add_argument("--all", action="store_true", help="display every match, no cap")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("neighbors", help="show a node and its connections")
    sp.add_argument("node", help="node id (relative path)")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--limit", type=int, default=0,
                    help="cap each direction to N rows (0 = all); reports the true totals")
    sp.set_defaults(func=cmd_neighbors)

    sp = sub.add_parser("impact", help="impact radius: who depends on a node / what it depends on")
    sp.add_argument("node", nargs="?", default=None,
                    help="node id (path or decision:ID); with --diff, the project path instead")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--diff", action="store_true",
                    help="blast radius of the uncommitted working-tree changes (no node needed)")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--up", action="store_true", help="only upstream (who depends on it)")
    grp.add_argument("--down", action="store_true", help="only downstream (what it depends on)")
    sp.add_argument("--depth", type=int, default=2, help="max BFS depth (default: 2)")
    sp.set_defaults(func=cmd_impact)

    sp = sub.add_parser("why", help="shortest path between two nodes (how are they connected?)")
    sp.add_argument("source", help="start node id (relative path or decision:ID)")
    sp.add_argument("target", help="end node id")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_why)

    sp = sub.add_parser("focus",
                        help="task-aware retrieval: minimal high-value subgraph within a budget")
    sp.add_argument("task", help="what you are working on (e.g. \"token budget in the report\")")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--budget", type=int, default=2000,
                    help="approx token budget for the returned node set (default: 2000)")
    sp.set_defaults(func=cmd_focus)

    sp = sub.add_parser("symbols", help="list function/class signatures in a Python file")
    sp.add_argument("file", help="path to a .py file (resolved under the project root)")
    sp.add_argument("path", nargs="?", default=".",
                    help="project root the file is resolved against (default: .)")
    sp.set_defaults(func=cmd_symbols)

    sp = sub.add_parser("export", help="export the graph to an interchange format (GraphML)")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--format", choices=["graphml"], default="graphml", help="output format")
    sp.add_argument("--out", help="write to this file instead of stdout")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("agent",
                        help="install/remove SB directive in CLAUDE.md/AGENTS.md + Claude hook")
    sp.add_argument("action", choices=["install", "uninstall"])
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_agent)

    sp = sub.add_parser("hook",
                        help="install/remove the git post-commit/post-checkout rebuild hook")
    sp.add_argument("action", choices=["install", "uninstall"])
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_hook)

    sp = sub.add_parser("hook-context", help="(internal) emit PreToolUse additionalContext JSON")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_hook_context)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
