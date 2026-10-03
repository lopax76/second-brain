"""The superior graph of a workspace (0.10): projects, general memory and agents' memories, linked.

The superior graph is the workspace root indexed like any project — but its walk skips the
project folders (each has its own graph), so its file nodes are exactly the files that belong to
NO project: the general memory. :func:`enrich` then adds, without loading any project graph:

* one ``project`` node per project, from the small ``riepilogo.json`` each project store keeps;
* one ``memory`` node per agent memory file (Claude Code, Codex), read-only, outside the tree;
* the links between them, resolved against the workspace:
  - a general file or a memory that cites a path inside a project  -> edge to that project;
  - a project whose files cite another project or a general file   -> project-to-project /
    project-to-file edge (from the ``external_refs`` its build recorded);
  - a Claude Code memory folder belongs to the project it was written for (its folder name is
    the project path, encoded) -> edge memory -> project;
  - general-file references that only LOOKED broken because they point into a project are
    resolved and removed from ``broken_refs``.

Everything is derived from files on disk; no source is ever written.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from second_brain.extract import extract_text, read_bytes_capped
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType
from second_brain.workspace import Project, Workspace

_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")


def project_node_id(p: Project) -> str:
    return f"progetto:{p.id}"


def _claude_key(path: Path) -> str:
    """How Claude Code names a project's memory folder: every non-alphanumeric char -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _memory_id(f: Path) -> str:
    home = Path.home()
    try:
        return "memoria:~/" + f.relative_to(home).as_posix()
    except ValueError:
        return "memoria:" + f.as_posix()


# Agents write paths in backticks (`Maestro\tools\backup.ps1`). The project indexer blanks
# inline code on purpose (fragments of code are not references), but in an agent's MEMORY a
# backticked path is the reference. Only spans that really look like a path are taken.
_CODE_SPAN = re.compile(r"`([^`\n]{3,300})`")
_PATHLIKE = re.compile(r"^(?:[A-Za-z]:[\\/]|~[\\/]|\.{1,2}[\\/])?[^\s*?<>|]+[\\/][^\s*?<>|]+$")


_ABS_IN_PROSE = re.compile(r"(?<![\w/\\])[A-Za-z]:[\\/][^\s`'\"<>|*?()\[\]]+")


def _code_paths(text: str) -> list[str]:
    """Paths an agent's memory cites: absolute paths in prose, and backticked spans that are
    paths (with a separator, and a file extension or a drive letter)."""
    out = [m.group(0).rstrip(".,;:") for m in _ABS_IN_PROSE.finditer(text)]
    for m in _CODE_SPAN.finditer(text):
        span = m.group(1).strip()
        last = re.split(r"[\\/]", span)[-1]
        if _PATHLIKE.match(span) and ("." in last or _DRIVE.match(span)):
            out.append(span)
    return out


def _resolve_target(target: str, base_dir: Path) -> Path | None:
    t = target.strip().strip("`'\"<>").replace("\\", "/")
    if not t or "://" in t:
        return None
    if _DRIVE.match(t):
        p = Path(t)
    elif t.startswith("~/"):
        p = Path(os.path.expanduser(t))
    else:
        p = base_dir / t
    try:
        return Path(os.path.normpath(p))
    except (OSError, ValueError):
        return None


class _Linker:
    def __init__(self, graph: Graph, ws: Workspace):
        self.g, self.ws = graph, ws
        self.root = ws.root
        self.resolved = 0

    def where(self, p: Path) -> str | None:
        """Node id in the superior graph for an absolute path, or None if outside it."""
        proj = self.ws.project_of(p)
        if proj is not None:
            return project_node_id(proj)
        try:
            rel = p.relative_to(self.root).as_posix()
        except ValueError:
            return None
        if rel in self.g.nodes:
            return rel
        # a folder: link to its area if present
        return None

    def link(self, source: str, target: str, base_dir: Path, *, why: str) -> bool:
        p = _resolve_target(target, base_dir)
        if p is None:
            return False
        dest = self.where(p)
        if dest is None or dest == source:
            return False
        meta = {"via": why}
        proj = self.ws.project_of(p)
        if proj is not None:
            try:
                meta["file"] = p.relative_to(proj.root).as_posix()
            except ValueError:
                pass
        if self.g.add_edge(Edge(source, dest, EdgeType.REFERENCES, meta)):
            self.resolved += 1
        return True


def enrich(graph: Graph, ws: Workspace) -> dict[str, int]:
    """Add projects, agent memories and cross links to the superior graph (in place)."""
    from second_brain import store

    lk = _Linker(graph, ws)
    stats = {"projects": 0, "memories": 0, "links": 0, "unbroken": 0}

    # 1. Project nodes, from each project's summary (no graph.json is loaded).
    summaries: dict[str, dict] = {}
    for p in ws.projects:
        s = store.load_summary(ws.project_store(p)) or {}
        summaries[p.id] = s
        node = Node(id=project_node_id(p), type=NodeType.PROJECT, label=p.name, path=None)
        node.meta.update({
            "rel": p.rel,
            "indexed": bool(s),
            "files": s.get("files"), "links": s.get("links"),
            "areas": s.get("areas", []), "key_files": s.get("key_files", []),
            "updated": s.get("updated"),
        })
        node.description = (f"progetto · {s['files']} file · aggiornato {s.get('updated')}"
                            if s else "progetto · grafo non ancora costruito")
        graph.add_node(node)
        stats["projects"] += 1

    # 2. General files whose "broken" references actually point into a project: resolve them.
    for nid, node in list(graph.nodes.items()):
        if not node.path:
            continue
        base = (ws.root / node.path).parent
        for key in ("broken_refs", "external_refs"):
            refs = node.meta.get(key)
            if not refs:
                continue
            left = [t for t in refs if not lk.link(nid, t, base, why=key)]
            if key == "broken_refs":
                stats["unbroken"] += len(refs) - len(left)
            if left:
                node.meta[key] = left
            else:
                node.meta.pop(key, None)

    # 3. Project -> project / general-file links, from the references each project recorded.
    for p in ws.projects:
        for t in summaries[p.id].get("external_refs", []):
            # external refs were recorded relative to a file we no longer know: resolve absolute
            # ones exactly, relative ones against the project root (best effort, said in meta)
            lk.link(project_node_id(p), t, p.root, why="external_refs")

    # 4. Agent memory files (Claude Code, Codex): nodes + what they cite + whose they are.
    keys = {_claude_key(pr.root): pr for pr in ws.projects}
    keys[_claude_key(ws.root)] = None  # memory of the workspace itself: no project edge
    for f in ws.memory_files():
        mid = _memory_id(f)
        node = Node(id=mid, type=NodeType.MEMORY, label=f.name, path=None)
        try:
            st = f.stat()
            node.meta.update({"abs_path": str(f), "size": st.st_size})
        except OSError:
            node.meta["abs_path"] = str(f)
        node.description = "memoria dell'agente · " + (
            "Claude Code" if "/.claude/" in f.as_posix() else
            "Codex" if "/.codex/" in f.as_posix() else "agenti")
        graph.add_node(node)
        stats["memories"] += 1
        parts = f.parts
        if "projects" in parts and "memory" in parts:  # ~/.claude/projects/<key>/memory/x.md
            owner_key = parts[parts.index("projects") + 1]
            if owner_key in keys and keys[owner_key] is not None:
                graph.add_edge(Edge(mid, project_node_id(keys[owner_key]), EdgeType.BELONGS_TO,
                                    {"via": "cartella memoria di Claude Code"}))
        data = read_bytes_capped(f)
        if data is None:
            continue
        text = data.decode("utf-8", errors="ignore")
        fe = extract_text(f.name, text)
        targets = [t for t, _ in fe.refs] + _code_paths(text)
        for target in targets:
            lk.link(mid, target, f.parent, why="memoria")

    stats["links"] = lk.resolved
    return stats


def extra_signature(ws: Workspace) -> dict[str, str]:
    """What the superior graph depends on beyond its own files: project summaries + memories.

    Folded into the superior store's freshness signature, so a rebuilt project or an edited
    memory makes the superior graph stale (and it is refreshed incrementally: only the cheap
    enrich step and the changed general files are redone).
    """
    sig: dict[str, str] = {}
    from second_brain import store
    for p in ws.projects:
        s = store.load_summary(ws.project_store(p))
        sig[f":progetto:{p.id}"] = (s or {}).get("digest", "assente")
    for f in ws.memory_files():
        try:
            st = f.stat()
            sig[f":memoria:{f.as_posix()}"] = f"{st.st_size}:{st.st_mtime_ns}"
        except OSError:
            continue
    return sig


__all__ = ["enrich", "extra_signature", "project_node_id"]

