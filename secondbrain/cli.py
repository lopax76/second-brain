"""Command-line interface: build, gate, view, stats, and the query commands.

Read-only on your sources: every command only reads the project and writes derived files
under ``.secondbrain/``.
"""

from __future__ import annotations

import argparse
import sys

from secondbrain import __version__, assess, gate, query, store
from secondbrain.freshness import build_manifest, index
from secondbrain.model import Graph
from secondbrain.viewer import write_view


def _human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _build(path: str) -> tuple[Graph, dict[str, str]]:
    # Single filesystem walk produces both the graph and the manifest.
    return index(path)


def _load_or_build(path: str) -> Graph:
    return store.load_graph(path) or _build(path)[0]


def cmd_build(args: argparse.Namespace) -> int:
    g, m = _build(args.path)
    store.save(args.path, g, m)
    c = g.counts()
    print(f"built '{g.project}': {len(g.nodes)} nodes, {len(g.edges)} edges")
    print("  nodes:", c["nodes"])
    print("  edges:", c["edges"])
    print(f"  store: {store.store_dir(args.path)}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    g = store.load_graph(args.path)
    old = store.load_manifest(args.path)
    if g is None or old is None:
        print("no graph found \u2014 run 'secondbrain build' first", file=sys.stderr)
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
    for r in res:
        print(f"  {r['type']:9} {r['id']}")
    print(f"({len(res)} matches)")
    return 0


def cmd_neighbors(args: argparse.Namespace) -> int:
    n = query.neighbors(_load_or_build(args.path), args.node)
    if n is None:
        print(f"node not found: {args.node}", file=sys.stderr)
        return 1
    print(f"{n['id']} ({n['type']}) \u00b7 {_human(n['size'])}")
    if n["description"]:
        print(f"  {n['description']}")
    if n["broken_refs"]:
        print(f"  broken refs: {n['broken_refs']}")
    print(f"  outgoing ({len(n['outgoing'])}):")
    for o in n["outgoing"]:
        print(f"    -{o['edge']}-> {o['id']} ({o['type']})")
    print(f"  incoming ({len(n['incoming'])}):")
    for o in n["incoming"]:
        print(f"    <-{o['edge']}- {o['id']} ({o['type']})")
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    r = assess.assess(args.path)
    out = store.store_dir(args.path)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "assessment.md"
    p.write_text(assess.render_markdown(r), encoding="utf-8")
    print(f"{r['project']}: {r['files']} files, {r['areas']} areas, {r['links']} links")
    print(f"  hidden: {r['truncated']} truncated, {r['empty']} empty, "
          f"{r['orphans']} orphans (~{r['orphans_pct']}%), {r['broken_refs']} broken, "
          f"{r['decisions']} decisions")
    print(f"  orient an assistant: ~{r['tokens_read_all_files']} tokens to read all files "
          f"(~{r['tokens_read_all_docs']} for docs) -> ~{r['tokens_digest']} with SB")
    print(f"  report: {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="secondbrain",
        description="Second Brain \u2014 a living, low-token map of a project.",
    )
    parser.add_argument("--version", action="version", version=f"second-brain {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn, help_text in [
        ("build", cmd_build, "index the project -> .secondbrain/graph.json"),
        ("gate", cmd_gate, "anti-drift check (broken refs, stale files, orphans)"),
        ("stats", cmd_stats, "quick counts by node/edge type"),
        ("map", cmd_map, "compact project digest (areas, sizes, most connected)"),
        ("assess", cmd_assess, "one-shot before/after report: problems + token savings"),
    ]:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("view", help="write a self-contained 3D viewer -> .secondbrain/view.html")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--backbone", action="store_true",
                    help="render only areas + knowledge-connected files (auto for huge graphs)")
    sp.set_defaults(func=cmd_view)

    sp = sub.add_parser("find", help="find nodes by name or path substring")
    sp.add_argument("query", help="substring to search for")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("neighbors", help="show a node and its connections")
    sp.add_argument("node", help="node id (relative path)")
    sp.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    sp.set_defaults(func=cmd_neighbors)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
