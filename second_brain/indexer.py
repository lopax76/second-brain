"""Build the project graph: typed file nodes, area clustering, and typed edges.

Edges produced in v1:
- ``imports``    — code -> code (Python via ``ast``, JS/TS relative specifiers best-effort)
- ``references`` — doc -> file (markdown link / wikilink / plain path-in-prose)
- ``belongs_to`` — file -> area (the top-level directory)

Reference resolution is conservative: a reference is recorded as *broken* only when it
points inside the project root and cannot be found, so the anti-drift gate stays trustworthy.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from pathlib import Path

from second_brain.classify import classify, rules_from_config
from second_brain.config import load_config
from second_brain.ignore import (
    DEFAULT_IGNORE_DIRS,
    GitRule,
    gitignored,
    is_ignored_dir,
    is_ignored_file,
    load_gitignore_rules,
    load_ignore_patterns,
)
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType
from second_brain.pycode import PyImport, js_imports, python_imports
from second_brain.pysymbols import extract as extract_symbol_calls
from second_brain.references import extract_references_tagged

_TEXT_EXTS = {
    ".md", ".markdown", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".json", ".jsonl", ".xml",
    ".html", ".htm", ".css", ".sql", ".ps1", ".psm1", ".sh", ".bash", ".go", ".rs",
    ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".cs",
}
_JS_EXTS = {".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"}
# Documentation references (links, wikilinks, path-in-prose) are extracted ONLY from
# documents. In source code, filename-looking strings are data, not references — scanning
# them produces noise, so we rely on import edges (ast) for code instead.
_DOC_REF_EXTS = {".md", ".markdown", ".rst", ".txt", ".html", ".htm"}
_JS_RESOLVE_ORDER = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", "/index.ts", "/index.js")
_MAX_READ_BYTES = 5_000_000

AREA_ROOT = "(root)"


def _ext(name: str) -> str:
    # os.path.splitext treats leading-dot names (".gitignore") as extensionless.
    return os.path.splitext(name)[1].lower()


def _is_reparse(path: str) -> bool:
    """True for symlinks and Windows junctions/reparse points (must not be descended into).

    ``os.walk`` skips POSIX directory symlinks, but on Windows a *junction* is not a symlink
    and ``os.walk`` would follow it — causing infinite loops / file explosion on a self- or
    parent-pointing junction. Detect the reparse-point attribute and skip it.
    """
    try:
        if os.path.islink(path):
            return True
        attrs = getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return True  # unreadable -> safest to skip


def gitignore_rules_for(root: Path) -> list[GitRule] | None:
    """Compiled root-``.gitignore`` rules when the project opts in (config ``respect_gitignore``),
    else ``None`` (the walk then ignores .gitignore entirely — byte-identical default)."""
    return load_gitignore_rules(root) if load_config(root).respect_gitignore else None


def iter_files(
    root: Path, patterns: list[str], git_rules: list[GitRule] | None = None
) -> list[str]:
    """Return sorted POSIX relative paths of indexable files under ``root``.

    ``os.walk`` does not follow directory symlinks, and junctions/reparse points are pruned
    explicitly (loop-safe on Windows too). An entry that cannot be expressed relative to
    ``root`` (exotic symlink/junction) is skipped, never aborting. When ``git_rules`` is given
    (project opted in to ``respect_gitignore``), files and directories matched by the root
    ``.gitignore`` are also skipped — pruning an ignored directory is correct (git cannot
    re-include a path under an excluded directory).
    """
    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        kept: list[str] = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if is_ignored_dir(d) or _is_reparse(full):
                continue
            if git_rules:
                try:
                    rel_d = Path(full).relative_to(root).as_posix()
                except ValueError:
                    rel_d = ""
                if rel_d and gitignored(rel_d, True, git_rules):
                    continue
            kept.append(d)
        dirnames[:] = kept
        for fn in filenames:
            try:
                rel = (Path(dirpath) / fn).relative_to(root).as_posix()
            except ValueError:
                continue
            if is_ignored_file(rel, fn, patterns):
                continue
            if git_rules and gitignored(rel, False, git_rules):
                continue
            rels.append(rel)
    return sorted(rels)


def _read_text(path: Path) -> str | None:
    ext = _ext(path.name)
    if ext and ext not in _TEXT_EXTS:
        return None
    try:
        if path.stat().st_size > _MAX_READ_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _top_area(rel: str) -> str:
    return rel.split("/", 1)[0] if "/" in rel else AREA_ROOT


def _python_module_map(py_files: list[str]) -> dict[str, str]:
    """Map dotted module/package -> file rel path for internal import resolution.

    A package (``__init__.py``) wins over a same-named module if both exist (matching
    Python's own resolution), regardless of iteration order.
    """
    mods: dict[str, str] = {}
    pkgs: dict[str, str] = {}
    for rel in py_files:
        parts = rel[:-3].split("/")  # drop ".py"
        if parts[-1] == "__init__":
            pkg = ".".join(parts[:-1])
            if pkg:
                pkgs[pkg] = rel
        else:
            mods[".".join(parts)] = rel
    return {**mods, **pkgs}


def _resolve_py(imp: PyImport, from_rel: str, module_map: dict[str, str]) -> list[str]:
    """Resolve one Python import to internal file rel paths (may be empty)."""
    mod_parts = from_rel[:-3].split("/")
    pkg_parts = mod_parts[:-1]  # package of the importing module
    cands: list[str] = []
    if imp.level == 0:
        if not imp.module:
            return []
        cands.append(imp.module)
        for n in imp.names:
            cands.append(f"{imp.module}.{n}")
    else:
        keep = len(pkg_parts) - (imp.level - 1)
        if keep < 0:
            return []  # relative import reaches above the project root: not resolvable
        base = pkg_parts[:keep]
        if imp.module:
            cand_parts = base + imp.module.split(".")
            cands.append(".".join(cand_parts))
            for n in imp.names:
                cands.append(".".join(cand_parts + [n]))
        else:
            for n in imp.names:
                cands.append(".".join(base + [n]))
    out: list[str] = []
    for c in cands:
        tgt = module_map.get(c)
        if tgt and tgt != from_rel and tgt not in out:
            out.append(tgt)
    return out


def _resolve_js(spec: str, from_rel: str, node_ids: set[str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), spec))
    for suffix in _JS_RESOLVE_ORDER:
        cand = base + suffix
        if cand in node_ids and cand != from_rel:
            return cand
    return None


# A reference target only "looks like a project file" if it has a path separator or a short
# file-like extension. This is the conservative guard that stops minified/inline code fragments
# in HTML docs (e.g. `](A)`, `](this.easingTime)` parsed as markdown links) from being reported
# as broken references. A real broken file link almost always has a '/' or a '.ext'.
# The extension must START with a letter, so version/number strings like `v1.2`, `1.2.3`, `2.36s`
# (a `.2` / `.36s` tail) are NOT mistaken for files (avoids false-positive broken refs in
# CHANGELOG/release notes). Real extensions like .md/.gz/.md5 still match.
_FILE_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


def _looks_like_path(target: str) -> bool:
    return "/" in target or bool(_FILE_EXT_RE.search(target))


def _is_external(target: str) -> bool:
    """True for URLs, Windows drive-letter paths, UNC paths, and POSIX absolute paths."""
    if "://" in target:
        return True
    if len(target) >= 2 and target[1] == ":" and target[0].isalpha():
        return True  # e.g. C:/Users/...
    # Any leading '/' is outside the project: POSIX absolute (/etc/hosts) or UNC (//server/share,
    # from a cleaned \\server\share). Marking these broken was a false positive in the gate.
    return target.startswith("/")


def _resolve_ref(
    target: str,
    kind: str,
    from_rel: str,
    node_ids: set[str],
    basename_index: dict[str, list[str]],
    stem_index: dict[str, list[str]],
    root_p: Path,
) -> tuple[str | None, bool]:
    """Resolve a documentation reference to a project file.

    Returns ``(resolved_id, is_broken)``. A reference is *broken* only when it is an
    intentional link/wikilink that targets a project-internal file which does not exist.
    Plain prose mentions (``kind == "path"``) are never broken (often library names or
    examples); external URLs/absolute paths and references into ignored dirs are skipped.
    """
    if not target:
        return None, False
    cand_file = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), target))
    cand_root = posixpath.normpath(target.lstrip("/"))
    for cand in (cand_file, cand_root):
        if cand in node_ids:
            return (cand if cand != from_rel else None), False
    base = target.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for index, key in ((basename_index, base), (stem_index, stem)):
        ids = [i for i in index.get(key, []) if i != from_rel]
        if len(ids) == 1:
            return ids[0], False

    # Unresolved: decide whether it is genuinely a broken link.
    if kind == "path" or _is_external(target):
        return None, False
    if cand_root.split("/", 1)[0] in DEFAULT_IGNORE_DIRS:
        return None, False
    if cand_root.startswith("../") or cand_file.startswith("../"):
        return None, False  # escapes the project root
    if kind == "wikilink" and not ("/" in target or "." in base):
        return None, False  # bare [[Concept]] is a concept link, not a file
    if not _looks_like_path(target):
        return None, False  # bare token (e.g. code fragment in an HTML doc), not a file ref
    # The target is not an indexed node, but it may be a REAL file we simply do not
    # index as a graph node (image/pdf/binary asset). A reference to an existing file
    # is NOT broken — only a reference to a missing file is. (Regression 2026-06-14:
    # the gate flagged README -> docs/assets/*.png as broken on a clean published repo.)
    for cand in (cand_file, cand_root):
        if cand and not cand.startswith("../") and (root_p / cand).is_file():
            return None, False
    return None, True


def _describe(node: Node, area: str, inbound: int) -> str:
    where = "root" if area == AREA_ROOT else f"area '{area}'"
    tail = f" · {inbound} inbound" if inbound else ""
    if node.type is NodeType.AREA:
        return f"area '{node.label}'"
    return f"{node.type.value} · {where}{tail}"


def _override_types(cfg) -> dict[str, NodeType]:
    """Resolve config type-overrides to {posix_path: NodeType}; unknown/AREA names are ignored."""
    by_value = {nt.value: nt for nt in NodeType}
    out: dict[str, NodeType] = {}
    for path, tname in cfg.type_overrides:
        nt = by_value.get(tname)
        if nt is not None and nt is not NodeType.AREA:
            out[path] = nt
    return out

def build_graph(
    root: str | os.PathLike[str],
    *,
    project: str | None = None,
    symbols: bool = False,
    _rels: list[str] | None = None,
) -> Graph:
    """Index the project at ``root`` and return its graph. Never modifies the project.

    ``symbols=True`` adds the opt-in symbol layer (function/class nodes + intra-file ``calls``
    edges) for Python files. ``_rels`` lets a caller pass a precomputed file list to avoid
    walking the tree twice (see :func:`second_brain.freshness.index`).
    """
    root_p = Path(root).resolve()
    if not root_p.is_dir():
        raise NotADirectoryError(f"not a directory: {root_p}")

    g = Graph(project=project or root_p.name)
    cfg = load_config(root_p)
    rules = rules_from_config(cfg)
    overrides = _override_types(cfg)
    if _rels is not None:
        rels = _rels
    else:
        rels = iter_files(root_p, load_ignore_patterns(root_p), gitignore_rules_for(root_p))

    # 1. File nodes + areas.
    areas: set[str] = set()
    for rel in rels:
        ntype = overrides.get(rel) or classify(rel, rules)
        label = rel.rsplit("/", 1)[-1]
        node = Node(id=rel, type=ntype, label=label, path=rel)
        try:
            node.meta["size"] = (root_p / rel).stat().st_size
        except OSError:
            pass
        g.add_node(node)
        areas.add(_top_area(rel))
    for area in sorted(areas):
        g.add_node(Node(id=f"area:{area}", type=NodeType.AREA, label=area))
    for rel in rels:
        g.add_edge(Edge(rel, f"area:{_top_area(rel)}", EdgeType.BELONGS_TO))

    # 2. Indexes for resolution.
    node_ids = set(g.nodes.keys())
    basename_index: dict[str, list[str]] = {}
    stem_index: dict[str, list[str]] = {}
    for rel in rels:
        base = rel.rsplit("/", 1)[-1]
        basename_index.setdefault(base, []).append(rel)
        stem = base.rsplit(".", 1)[0] if "." in base else base
        stem_index.setdefault(stem, []).append(rel)
    py_files = [r for r in rels if _ext(r) == ".py"]
    module_map = _python_module_map(py_files)
    py_text: dict[str, str] = {}  # .py contents cached during edge build, reused by the symbol pass

    # 3. Edges from file contents. Only code (imports) and docs (references) are ever READ;
    #    data/config/binaries are never opened - the graph needs only their type/size/area.
    #    This is what keeps indexing light on data-heavy projects (no reading huge JSON/CSV/logs).
    for rel in rels:
        ext = _ext(rel)
        is_code = ext == ".py" or ext in _JS_EXTS
        is_doc = ext in _DOC_REF_EXTS
        if not (is_code or is_doc):
            continue
        text = _read_text(root_p / rel)
        if text is None:
            continue
        if ext == ".py":
            py_text[rel] = text  # reuse in the symbol pass (3b) instead of reading twice
            for imp in python_imports(text):
                for tgt in _resolve_py(imp, rel, module_map):
                    g.add_edge(Edge(rel, tgt, EdgeType.IMPORTS))
        elif ext in _JS_EXTS:
            for spec in js_imports(text):
                tgt = _resolve_js(spec, rel, node_ids)
                if tgt:
                    g.add_edge(Edge(rel, tgt, EdgeType.IMPORTS))
        if ext in _DOC_REF_EXTS:
            broken: list[str] = []
            for target, kind in extract_references_tagged(text):
                resolved, is_broken = _resolve_ref(
                    target, kind, rel, node_ids, basename_index, stem_index, root_p
                )
                if resolved:
                    g.add_edge(Edge(rel, resolved, EdgeType.REFERENCES))
                elif is_broken:
                    broken.append(target)
            if broken:
                g.nodes[rel].meta["broken_refs"] = broken

    # 3b. Optional symbol layer: function/class nodes + intra-file `calls` edges (opt-in; off by
    #     default to keep the file-level map small). Symbol nodes carry no `path` (they are
    #     sub-file entities, not files), so file counts/areas/orphans are unaffected. Cross-file
    #     calls are intentionally not linked (no type inference) — `imports` already carries that.
    if symbols:
        for rel in py_files:
            text = py_text.get(rel)  # already read during the edge pass (no second disk read)
            if text is None:
                continue
            sym_defs, sym_calls = extract_symbol_calls(text)
            for d in sym_defs:
                sid = f"{rel}::{d.qualname}"
                g.add_node(Node(id=sid, type=NodeType.SYMBOL,
                                label=d.qualname.rsplit(".", 1)[-1],
                                meta={"file": rel, "line": d.line, "kind": d.kind,
                                      "qualname": d.qualname}))
                g.add_edge(Edge(rel, sid, EdgeType.DEFINES))
            for caller_q, callee_q in sym_calls:
                g.add_edge(Edge(f"{rel}::{caller_q}", f"{rel}::{callee_q}", EdgeType.CALLS))

    # 4. Descriptions (after edges, so we can include inbound counts).
    inbound: dict[str, int] = {}
    for e in g.edges:
        if e.type in (EdgeType.REFERENCES, EdgeType.IMPORTS):
            inbound[e.target] = inbound.get(e.target, 0) + 1
    for node in g.nodes.values():
        area = _top_area(node.path) if node.path else AREA_ROOT
        node.description = _describe(node, area, inbound.get(node.id, 0))

    return g
