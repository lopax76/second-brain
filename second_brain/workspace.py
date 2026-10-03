"""The workspace: one folder holding many projects, and the graph hierarchy over it (0.10).

A workspace is a directory with a ``.secondbrain-workspace.json`` file (``second-brain workspace
init`` writes one). Under it:

* every **project** (a top-level folder carrying a project marker, or one listed explicitly) has
  its OWN graph and store, ``<ws>/.secondbrain/progetti/<id>/``, with its own write lock — so two
  agents working on two projects never touch each other's graph;
* the **superior graph** lives in ``<ws>/.secondbrain/superiore/``: one node per project, every
  file that belongs to no project (the general memory: notes, instructions, tools, reports), the
  agents' memory files (Claude Code, Codex), and the links between all of them.

The workspace file is plain JSON, every key optional::

    {
      "progetti": "auto",                 // or a list: ["web-app", "docs-site", ...]
      "aggiungi": ["Maestro/tools"],      // extra project roots (also nested ones)
      "escludi":  ["old-archive", "Pictures"],   // never indexed at all
      "memorie":  ["~/.claude/CLAUDE.md", "~/.claude/projects/*/memory/*.md",
                   "~/.codex/memories/**/*.md", "~/.codex/AGENTS.md"]
    }

Everything here is read-only on the user's files; only the store under ``.secondbrain`` is written.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

WORKSPACE_FILE = ".secondbrain-workspace.json"
STORE_DIRNAME = ".secondbrain"

# What makes a top-level folder a project when "progetti" is "auto".
PROJECT_MARKERS = (".git", "PROGETTO.md", "CLAUDE.md", "AGENTS.md", "pyproject.toml",
                   "package.json", "project.godot", "Cargo.toml", "go.mod")

DEFAULT_MEMORY = (
    "~/.claude/CLAUDE.md",
    "~/.claude/projects/*/memory/*.md",
    "~/.codex/AGENTS.md",
    "~/.codex/memories/**/*.md",
    "~/.agents/AGENTS.md",
)


def slug(name: str) -> str:
    """A stable, filesystem-safe project id from a folder path: «Second Brain» -> «second-brain»."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("\\", "/").replace("/", "--")).strip("-")
    return s or "progetto"


@dataclass(frozen=True)
class Project:
    id: str
    rel: str           # POSIX path relative to the workspace root
    root: Path

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass
class Workspace:
    root: Path
    projects: list[Project] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)    # POSIX rel dirs, never indexed
    memory: list[str] = field(default_factory=list)     # glob patterns (may start with ~)

    # --- stores -----------------------------------------------------------------------------
    @property
    def store_root(self) -> Path:
        return self.root / STORE_DIRNAME

    def project_store(self, p: Project) -> Path:
        return self.store_root / "progetti" / p.id

    @property
    def superior_store(self) -> Path:
        return self.store_root / "superiore"

    # --- lookups ----------------------------------------------------------------------------
    def project_at(self, path: str | os.PathLike[str]) -> Project | None:
        """The project whose ROOT is exactly ``path``."""
        p = Path(path).resolve()
        for pr in self.projects:
            if pr.root == p:
                return pr
        return None

    def project_of(self, path: str | os.PathLike[str]) -> Project | None:
        """The deepest project containing ``path`` (a file or folder), or None."""
        p = Path(path).resolve()
        best: Project | None = None
        for pr in self.projects:
            if p == pr.root or pr.root in p.parents:
                if best is None or len(pr.root.parts) > len(best.root.parts):
                    best = pr
        return best

    def project_by_id(self, ident: str) -> Project | None:
        key = slug(ident)
        for pr in self.projects:
            if pr.id == key or pr.rel == ident or pr.name == ident:
                return pr
        return None

    def pruned_dirs(self) -> set[str]:
        """POSIX rel dirs the SUPERIOR walk must skip: projects (own graphs) and exclusions."""
        return {p.rel for p in self.projects} | set(self.exclude)

    def memory_files(self) -> list[Path]:
        """The agents' memory files that exist now, sorted, de-duplicated."""
        out: set[Path] = set()
        for pat in self.memory:
            pat = os.path.expanduser(pat)
            base, _, rest = pat.partition("*")
            if not rest:  # a plain file
                if os.path.isfile(pat):
                    out.add(Path(pat).resolve())
                continue
            anchor = Path(base).parent if not base.endswith(("/", "\\")) else Path(base)
            if not anchor.is_dir():
                continue
            rel_pat = Path(pat).relative_to(anchor).as_posix()
            for f in anchor.glob(rel_pat):
                if f.is_file():
                    out.add(f.resolve())
        return sorted(out)


def detect_projects(root: Path, exclude: set[str] | None = None) -> list[str]:
    """Top-level folders carrying a project marker (not hidden, not a junction/symlink)."""
    exclude = exclude or set()
    found: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return found
    for e in entries:
        hidden = e.name.startswith((".", "_"))
        if hidden or e.name in exclude or not e.is_dir(follow_symlinks=False):
            continue
        try:
            if e.is_junction() or e.is_symlink():  # Windows junctions: Immagini, Musica, Video
                continue
        except (AttributeError, OSError):
            pass
        if any((Path(e.path) / m).exists() for m in PROJECT_MARKERS):
            found.append(e.name)
    return found


def _read_config(root: Path) -> dict:
    try:
        data = json.loads((root / WORKSPACE_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(root: str | os.PathLike[str]) -> Workspace:
    """Read the workspace at ``root`` (the folder holding the workspace file)."""
    root_p = Path(root).resolve()
    cfg = _read_config(root_p)
    exclude = [str(x).strip("/").replace("\\", "/") for x in cfg.get("escludi", [])]
    listed = cfg.get("progetti", "auto")
    rels = detect_projects(root_p, set(exclude)) if listed == "auto" else [str(x) for x in listed]
    rels += [str(x) for x in cfg.get("aggiungi", [])]
    seen: set[str] = set()
    projects: list[Project] = []
    for rel in rels:
        rel = rel.strip("/").replace("\\", "/")
        if not rel or rel in seen or not (root_p / rel).is_dir():
            continue
        seen.add(rel)
        projects.append(Project(id=slug(rel), rel=rel, root=(root_p / rel).resolve()))
    memory = [str(x) for x in cfg.get("memorie", DEFAULT_MEMORY)]
    return Workspace(root=root_p, projects=projects, exclude=exclude, memory=memory)


# find_workspace is called on every store lookup: cache it, keyed on the workspace file's mtime
# so an edit to the file (a new project, an exclusion) is picked up without restarting a server.
_CACHE: dict[str, tuple[int, Workspace | None]] = {}


def find_workspace(path: str | os.PathLike[str]) -> Workspace | None:
    """The workspace containing ``path`` (walking up), or None if there is none."""
    p = Path(path).resolve()
    for cand in (p, *p.parents):
        f = cand / WORKSPACE_FILE
        try:
            mtime = f.stat().st_mtime_ns
        except OSError:
            continue
        key = str(cand)
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        ws = load(cand)
        _CACHE[key] = (mtime, ws)
        return ws
    return None


def init(root: str | os.PathLike[str], *, exclude: list[str] | None = None) -> Path:
    """Write a workspace file listing the detected projects (never overwrites an existing one)."""
    root_p = Path(root).resolve()
    f = root_p / WORKSPACE_FILE
    if f.exists():
        return f
    ex = exclude or []
    data = {"progetti": "auto", "aggiungi": [], "escludi": ex, "memorie": list(DEFAULT_MEMORY),
            "_rilevati": detect_projects(root_p, set(ex))}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _CACHE.pop(str(root_p), None)
    return f


__all__ = ["WORKSPACE_FILE", "Project", "Workspace", "detect_projects", "find_workspace",
           "init", "load", "slug"]
