"""GRAPH_REPORT.md — the one-pager an agent reads first, instead of grepping the whole project.

Distilled from the graph: scale + token cost, the god nodes (most-connected files), the
auto-discovered communities, the surprising cross-community links, the recorded decisions by
family, a few suggested questions, and the open problems (truncated / empty / orphan / broken).
Everything is deterministic and derived from the graph — no file contents — so the report is
safe to commit, diff, and read on every session for a few hundred tokens.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from second_brain import assess, communities, query
from second_brain.model import Graph, NodeType
from second_brain.store import store_dir

_GOD_NODES = 10
_KEY_FILES = 4
_SURPRISING = 8
_FAMILY_RE = re.compile(r"^(.*?)-\d+$")


def _tok(chars: int) -> int:
    return round(chars / 4)


def _human(n: int) -> str:
    f = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or u == "TB":
            return f"{f:.0f} {u}" if u == "B" else f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} TB"


def _family(decision_id: str) -> str:
    m = _FAMILY_RE.match(decision_id)
    return m.group(1) if m else decision_id


def _decision_families(graph: Graph) -> list[tuple[str, int]]:
    fams: dict[str, int] = {}
    for n in graph.nodes.values():
        if n.type is NodeType.DECISION:
            fam = _family(n.label)
            fams[fam] = fams.get(fam, 0) + 1
    return sorted(fams.items(), key=lambda kv: (-kv[1], kv[0]))


def _suggested_questions(
    god: list[dict], summaries: list[dict], surprising: list[dict]
) -> list[str]:
    """A few high-leverage questions, derived deterministically from the structure."""
    qs: list[str] = []
    if god:
        qs.append(f"What breaks if you change `{god[0]['id']}`? (run `impact {god[0]['id']}`)")
    if len(god) > 1:
        qs.append(f"How does `{god[1]['id']}` connect to the rest of the project?")
    if surprising:
        s = surprising[0]
        qs.append(
            f"Why does `{s['source']}` ({s['source_community']}) link to "
            f"`{s['target']}` ({s['target_community']})?"
        )
    if summaries and summaries[0]["key_files"]:
        c = summaries[0]
        qs.append(f"What is {c['name']} responsible for? (key file `{c['key_files'][0]}`)")
    qs.append("Is anything stale or orphaned? (run `second-brain gate`)")
    return qs


_DIGEST_SENTINEL = "\x00DIGEST\x00"  # replaced at the end with this report's own token cost


def render_report(
    graph: Graph,
    *,
    root: str | os.PathLike[str] | None = None,
    scan_problems: bool = True,
) -> str:
    """Render the graph as a single Markdown one-pager (deterministic).

    ``scan_problems=False`` skips the per-file integrity scan (truncated/empty) — used by ``build``
    to stay light — while still reporting the free broken-ref / orphan signals from the graph.
    """
    m = query.project_map(graph, top=_GOD_NODES)
    comm = communities.detect(graph)
    summaries = communities.summarize(graph, comm, key_files=_KEY_FILES)
    surprising = communities.surprising_edges(graph, comm, top=_SURPRISING)
    god = m["most_connected"]
    fams = _decision_families(graph)

    size = m["size"]
    tokens_all = _tok(size)

    out: list[str] = [
        f"# Second Brain — graph report: `{graph.project}`",
        "",
        "Auto-generated, read-only map. Read this before grepping the project; then query with "
        "`second-brain map/find/neighbors/impact`.",
        "",
        "## Scale",
        "",
        f"- **{m['files']} files** in **{m['areas']} areas**, "
        f"**{m['communities']} communities**, **{m['links']} links**, {_human(size)}",
        f"- orient an assistant: ~**{tokens_all:,} tokens** to read every file "
        f"-> ~**{_DIGEST_SENTINEL} tokens** to read this report",
        "",
        "## God nodes (most connected)",
        "",
    ]
    out += [f"- `{x['id']}` ({x['type']}) — {x['degree']} links" for x in god] or ["- (none)"]

    out += [
        "", "## Communities", "",
        "Auto-discovered from how files actually link (not from folders).", "",
    ]
    if summaries:
        for c in summaries:
            kf = ", ".join(f"`{k}`" for k in c["key_files"]) or "—"
            dom = ", ".join(c["dominant_types"]) or "—"
            out.append(
                f"- **{c['name']}** — {c['size']} files, cohesion {c['cohesion']}; "
                f"types: {dom}; key: {kf}"
            )
    else:
        out.append("- (none)")

    out += [
        "", "## Surprising connections", "",
        "Cross-community links — dependencies you would not guess from the folder layout.", "",
    ]
    if surprising:
        for s in surprising:
            out.append(
                f"- `{s['source']}` ({s['source_community']}) "
                f"-{s['type']}-> `{s['target']}` ({s['target_community']})"
            )
    else:
        out.append("- (none)")

    out += [
        "", "## Decisions", "",
        f"- **{m['node_types'].get('decision', 0)}** recorded decisions, by family:",
    ]
    if fams:
        out += [f"  - {fam}: {cnt}" for fam, cnt in fams]
    else:
        out.append("  - (none found)")

    out += ["", "## Suggested questions", ""]
    out += [f"- {q}" for q in _suggested_questions(god, summaries, surprising)]

    out += ["", "## Problems", ""]
    problems: list[str] = []
    if root is not None and scan_problems:
        integ = assess.scan_integrity(root, graph)
        if integ["truncated"]:
            problems.append(f"- **{len(integ['truncated'])}** truncated/corrupted files")
        if integ["empty"]:
            problems.append(f"- **{len(integ['empty'])}** empty files")
    elif not scan_problems:
        problems.append("- *(file-integrity scan skipped — run `second-brain report` or "
                        "`second-brain assess` to check for truncated/empty files)*")
    if m["broken_refs"]:
        problems.append(f"- **{m['broken_refs']}** broken references")
    if m["orphans"]:
        problems.append(f"- **{m['orphans']}** orphan files (linked to nothing)")
    out += problems or ["- none detected"]

    out += ["", "*Generated by `second-brain report` (read-only).*", ""]
    rendered = "\n".join(out)
    # Honest token cost = the size of THIS report (what an assistant actually reads), not a
    # synthetic sub-digest. Computed after rendering, then substituted into the Scale line.
    tokens_digest = max(1, _tok(len(rendered) - len(_DIGEST_SENTINEL)))
    return rendered.replace(_DIGEST_SENTINEL, f"{tokens_digest:,}")


def write_report(root: str | os.PathLike[str], graph: Graph, *, scan: bool = True) -> Path:
    """Write ``<root>/.secondbrain/GRAPH_REPORT.md`` and return its path.

    ``scan=False`` skips the per-file integrity scan (so ``build`` stays light); the report still
    reports broken refs and orphans, and notes that the integrity scan was skipped.
    """
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "GRAPH_REPORT.md"
    out.write_text(render_report(graph, root=root, scan_problems=scan),
                   encoding="utf-8", newline="\n")
    return out


__all__ = ["render_report", "write_report"]
