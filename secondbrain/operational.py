"""Operational nodes: decisions and work sessions, layered onto the file graph.

Decisions are recorded-decision identifiers found in documents (e.g. ``D-SB-1``, ``ADR-0007``,
``RFC-12``) - each becomes a node, linked from every document that mentions it. Sessions are
git commits (when the project is a git repository) - each becomes a node linked to the files
it touched. Both are best-effort and read-only; with no git, sessions are simply skipped.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from secondbrain.model import Edge, EdgeType, Graph, Node, NodeType

_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".html", ".htm"}
DECISION_RE = re.compile(r"\b(?:D-[A-Z]{1,8}-\d{1,5}|ADR-\d{1,5}|RFC-\d{1,5})\b")
_MAX_READ = 5_000_000


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def add_decisions(graph: Graph, root: str | os.PathLike[str]) -> None:
    """Create a decision node per unique decision id found in documents, with mentions edges."""
    root_p = Path(root)
    doc_ids = [n.id for n in list(graph.nodes.values())
               if n.path and _ext(n.path) in _DOC_EXTS]
    for rel in doc_ids:
        p = root_p / rel
        try:
            if p.stat().st_size > _MAX_READ:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        seen: set[str] = set()
        for m in DECISION_RE.finditer(text):
            did = m.group(0)
            if did in seen:
                continue
            seen.add(did)
            nid = f"decision:{did}"
            if nid not in graph.nodes:
                graph.add_node(Node(id=nid, type=NodeType.DECISION, label=did,
                                    description=f"decision {did}"))
            graph.add_edge(Edge(rel, nid, EdgeType.MENTIONS))


def add_sessions(graph: Graph, root: str | os.PathLike[str], *, limit: int = 40) -> None:
    """Create a session node per recent git commit, with touches edges to the files changed."""
    root_p = Path(root)
    if not (root_p / ".git").exists():
        return
    limit = max(1, int(limit))
    fmt = "%x01%h%x1f%s%x1f%aI%x1f%an"
    try:
        out = subprocess.run(
            # core.quotePath=false: keep non-ASCII paths (accented filenames) verbatim so
            # they match the graph node ids, instead of git's octal-escaped quoting.
            ["git", "-c", "core.quotePath=false", "-C", str(root_p), "log",
             f"-{limit}", "--no-merges", "--name-only", f"--pretty=format:{fmt}"],
            # Decode git's bytes as UTF-8 explicitly: text=True would use the Windows locale
            # (cp1252), re-mangling the accented paths that core.quotePath=false preserved.
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if out.returncode != 0:
        return
    node_ids = set(graph.nodes.keys())
    for blk in out.stdout.split("\x01"):
        blk = blk.strip("\n")
        if not blk:
            continue
        head, _, files_part = blk.partition("\n")
        parts = head.split("\x1f")
        if not parts or not parts[0]:
            continue
        h = parts[0]
        subj = parts[1] if len(parts) > 1 else ""
        date = parts[2] if len(parts) > 2 else ""
        author = parts[3] if len(parts) > 3 else ""
        nid = f"session:{h}"
        if nid not in graph.nodes:
            label = (f"{h} {subj}").strip()[:80]
            graph.add_node(Node(id=nid, type=NodeType.SESSION, label=label,
                                description=f"commit {h} by {author} {date[:10]}".strip(),
                                meta={"date": date, "author": author, "subject": subj}))
        for fpath in files_part.split("\n"):
            fpath = fpath.strip()
            if fpath and fpath in node_ids:
                graph.add_edge(Edge(nid, fpath, EdgeType.TOUCHES))


def enrich(graph: Graph, root: str | os.PathLike[str]) -> None:
    """Add operational nodes (decisions + sessions) onto an existing graph, in place."""
    add_decisions(graph, root)
    add_sessions(graph, root)
