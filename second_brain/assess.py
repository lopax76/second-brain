"""One-shot project assessment: what Second Brain reveals, and what it saves.

``second-brain assess`` indexes a project read-only and writes a before/after report a user can
run on their own codebase before adopting the tool: hidden problems (truncated/empty/orphan
files, broken links), the project's scale, the decisions and cross-references it surfaces, and
the token cost of orienting an assistant WITHOUT vs WITH Second Brain. The single most useful
thing for someone deciding whether it is worth installing.
"""

from __future__ import annotations

import os
from pathlib import Path

from second_brain import query
from second_brain.freshness import index
from second_brain.model import Graph, NodeType

_TEXT_EXTS = {
    ".md", ".markdown", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".jsonl",
    ".html", ".htm", ".css", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".xml", ".sql", ".ps1",
    ".psm1", ".sh", ".log", ".csv", ".go", ".rs", ".java", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".cs",
}
_DOC_TYPES = {
    NodeType.STRUCTURE, NodeType.REPORT, NodeType.DESIGN, NodeType.DECISION, NodeType.MEMORY,
}
_SCAN_CAP = 2_000_000
_LIST_CAP = 50  # how many truncated/empty file names to record in the report


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


_NULL_RUN = b"\x00" * 16  # a contiguous null run this long = zero-fill/truncation, not encoding


def _is_corrupt(chunk: bytes) -> bool:
    """True only on a CONTIGUOUS run of null bytes (zero-fill) — the unambiguous signature of a
    truncated / zero-filled file.

    Scattered or alternating null bytes are an ENCODING artifact (UTF-16, or files that mix
    UTF-8 and UTF-16 sections — e.g. trigger logs written by PowerShell), i.e. valid text, and
    are never flagged. Fix 0.1.2: the previous heuristic false-positived on such short
    mixed-encoding logs when their UTF-16 portion fell below the alternating-null ratio it
    looked for; a contiguous null run cannot occur in any text encoding, so it is the only
    safe signal of real truncation.
    """
    return _NULL_RUN in chunk


def scan_integrity(root: str | os.PathLike[str], graph: Graph) -> dict[str, list[str]]:
    """Find empty (zero-byte) and truncated/corrupted (null-byte) files among indexed nodes.

    Empty ``__init__.py`` files are excluded - they are conventionally empty, not a problem.
    """
    root_p = Path(root)
    empty: list[str] = []
    truncated: list[str] = []
    for n in graph.nodes.values():
        if not n.path:
            continue
        p = root_p / n.path
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        if sz == 0:
            if os.path.basename(n.path) != "__init__.py":
                empty.append(n.path)
            continue
        if _ext(n.path) in _TEXT_EXTS:
            try:
                with open(p, "rb") as f:
                    head = f.read(_SCAN_CAP)
                    tail = b""
                    if sz > _SCAN_CAP:  # also scan the file's end, where zero-fill usually lands
                        f.seek(-min(65536, sz), os.SEEK_END)
                        tail = f.read()
            except OSError:
                continue
            if _is_corrupt(head) or _NULL_RUN in tail:
                truncated.append(n.path)
    return {"empty": sorted(empty), "truncated": sorted(truncated)}


def _tok(chars: int) -> int:
    return round(chars / 4)


def _human(n: int) -> str:
    f = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or u == "TB":
            return f"{f:.0f} {u}" if u == "B" else f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} TB"


def _digest_text(m: dict) -> str:
    lines = [f"{m['project']}: {m['files']} files, {m['areas']} areas, {m['links']} links"]
    for a in m["by_area"]:
        lines.append(f"{a['area']}: {a['files']} files {a['size']}B [{','.join(a['top_types'])}]")
    for x in m["most_connected"]:
        lines.append(f"{x['degree']} {x['id']} {x['type']}")
    return "\n".join(lines)


def assess(root: str | os.PathLike[str]) -> dict:
    """Run the read-only assessment and return all metrics as plain data."""
    root_p = Path(root).resolve()
    graph, _ = index(root_p)
    m = query.project_map(graph, top=10)
    integ = scan_integrity(root_p, graph)
    files = [n for n in graph.nodes.values() if n.path]
    inventory_chars = sum(len(n.path) + 1 for n in files)
    doc_bytes = sum(int(n.meta.get("size", 0)) for n in files if n.type in _DOC_TYPES)
    graph_bytes = len(graph.to_json(indent=None).encode("utf-8"))
    digest_chars = len(_digest_text(m))
    orphans_pct = round(100 * m["orphans"] / max(1, m["files"]))
    return {
        "project": graph.project,
        "files": m["files"], "areas": m["areas"], "links": m["links"], "size": m["size"],
        "node_types": m["node_types"], "edge_types": m["edge_types"],
        "decisions": m["node_types"].get("decision", 0),
        "sessions": m["node_types"].get("session", 0),
        "orphans": m["orphans"], "orphans_pct": orphans_pct, "broken_refs": m["broken_refs"],
        "empty": len(integ["empty"]), "truncated": len(integ["truncated"]),
        "empty_files": integ["empty"][:_LIST_CAP],
        "truncated_files": integ["truncated"][:_LIST_CAP],
        "most_connected": m["most_connected"], "by_area": m["by_area"],
        "tokens_inventory": _tok(inventory_chars),
        "tokens_read_all_docs": _tok(doc_bytes),
        "tokens_read_all_files": _tok(m["size"]),
        "tokens_digest": _tok(digest_chars),
        "graph_bytes": graph_bytes,
    }


def _file_lines(names: list[str], total: int) -> list[str]:
    """Indented bullets listing file names, with an '...and N more' when capped."""
    out = [f"  - `{n}`" for n in names]
    if total > len(names):
        out.append(f"  - ...and {total - len(names)} more")
    return out


def render_markdown(r: dict) -> str:
    """Render an assessment dict as a Markdown before/after report."""
    digest = max(1, r["tokens_digest"])
    orient = max(r["tokens_read_all_docs"], r["tokens_inventory"])  # cheapest realistic orient
    factor = round(orient / digest) if orient > digest else None
    saving = (
        f"- **~{factor}x less** than reading the docs to get oriented - and roughly constant "
        "as the project grows"
        if factor
        else "- at this scale the digest already costs no more than just listing the files"
    )
    types = ", ".join(f"{k} {v}" for k, v in sorted(r["node_types"].items(), key=lambda kv: -kv[1]))
    out = [
        f"# Second Brain - assessment of `{r['project']}`",
        "",
        "Read-only snapshot. Re-run after changes; use `second-brain gate` to catch drift.",
        "",
        "## Scale",
        "",
        f"- **{r['files']} files** in **{r['areas']} areas**, **{r['links']} links**, "
        f"{_human(r['size'])}",
        f"- node types: {types}",
        "",
        "## What was hidden (before Second Brain)",
        "",
        f"- **{r['truncated']}** truncated/corrupted files (null bytes)",
        *_file_lines(r.get("truncated_files", []), r["truncated"]),
        f"- **{r['empty']}** empty files (zero bytes)",
        *_file_lines(r.get("empty_files", []), r["empty"]),
        f"- **{r['orphans']}** orphan files (~{r['orphans_pct']}%) - linked to nothing",
        f"- **{r['broken_refs']}** broken references",
        f"- **{r['decisions']}** decisions scattered in docs - now queryable nodes",
        "",
        "## Token cost to orient an assistant",
        "",
        f"- WITHOUT Second Brain: ~**{r['tokens_read_all_files']:,} tokens** to read every "
        f"indexed file, ~{r['tokens_read_all_docs']:,} for just the documents, or "
        f"~{r['tokens_inventory']:,} just to list every file's location",
        f"- WITH Second Brain: ~**{r['tokens_digest']:,} tokens** (the `map` digest); the full "
        f"index is {_human(r['graph_bytes'])}, queried on demand and never loaded into context",
        saving,
        "",
        "## Most connected files",
        "",
    ]
    for x in r["most_connected"]:
        out.append(f"- {x['degree']:>3}  `{x['id']}` ({x['type']})")
    out += ["", "*Generated by `second-brain assess` (read-only).*", ""]
    return "\n".join(out)
