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
from pathlib import Path

from second_brain.classify import classify
from second_brain.ignore import (
    DEFAULT_IGNORE_DIRS,
    is_ignored_dir,
    is_ignored_file,
    load_ignore_patterns,
)
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType
from second_brain.pycode import PyImport, js_imports, python_imports
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


def iter_files(root: Path, patterns: list[str]) -> list[str]:
    """Return sorted POSIX relative paths of indexable files under ``root``.

    ``os.walk`` does not follow directory symlinks (loop-safe). An entry that cannot be
    expressed relative to ``root`` (exotic symlink/junction) is skipped, never aborting.
    """
    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_ignored_dir(d)]
        for fn in filenames:
            try:
                rel = (Path(dirpath) / fn).relative_to(root).as_posix()
            except ValueError:
                continue
            if is_ignored_file(rel, fn, patterns):
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


def _is_external(target: str) -> bool:
    """True for URLs, Windows drive-letter paths, and UNC paths (cleaned form uses '/')."""
    if "://" in target:
        return True
    if len(target) >= 2 and target[1] == ":" and target[0].isalpha():
        return True  # e.g. C:/Users/...
    return target.startswith("//")  # UNC (\\server\share -> //server/share after cleaning)


def _resolve_ref(
    target: str,
    kind: str,
    from_rel: str,
    node_ids: set[str],
    basename_index: dict[str, list[str]],
    stem_index: dict[str, list[str]],
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
    return None, True


def _describe(node: Node, area: str, inbound: int) -> str:
    where = "root" if area == AREA_ROOT else f"area '{area}'"
    tail = f" · {inbound} inbound" if inbound else ""
    if node.type is NodeType.AREA:
        return f"area '{node.label}'"
    return f"{node.type.value} · {where}{tail}"


def build_graph(
    root: str | os.PathLike[str],
    *,
    project: str | None = None,
    _rels: list[str] | None = None,
) -> Graph:
    """Index the project at ``root`` and return its graph. Never modifies the project.

    ``_rels`` lets a caller pass a precomputed file list to avoid walking the tree twice
    (see :func:`second_brain.freshness.index`).
    """
    root_p = Path(root).resolve()
    if not root_p.is_dir():
        raise NotADirectoryError(f"not a directory: {root_p}")

    rels = _rels if _rels is not None else iter_files(root_p, load_ignore_patterns(root_p))
    g = Graph(project=project or root_p.name)

    # 1. File nodes + areas.
    areas: set[str] = set()
    for rel in rels:
        ntype = classify(rel)
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
                    target, kind, rel, node_ids, basename_index, stem_index
                )
                if resolved:
                    g.add_edge(Edge(rel, resolved, EdgeType.REFERENCES))
                elif is_broken:
                    broken.append(target)
            if broken:
                g.nodes[rel].meta["broken_refs"] = broken

    # 4. Descriptions (after edges, so we can include inbound counts).
    inbound: dict[str, int] = {}
    for e in g.edges:
        if e.type in (EdgeType.REFERENCES, EdgeType.IMPORTS):
            inbound[e.target] = inbound.get(e.target, 0) + 1
    for node in g.nodes.values():
        area = _top_area(node.path) if node.path else AREA_ROOT
        node.description = _describe(node, area, inbound.get(node.id, 0))

    return g
