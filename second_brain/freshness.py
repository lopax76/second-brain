"""Content-hash freshness + the single-walk ``index`` entry point.

Hashing uses the standard-library BLAKE2b (fast, no dependency). For text files the hash is
computed on newline-normalized bytes so a CRLF<->LF flip (e.g. a git checkout on Windows)
does not look like a content change. The manifest is a small ``{relative_path: hash}`` map
stored next to the graph; diffing it against the current files tells the gate whether the
brain is still in sync with the project.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from pathlib import Path

from second_brain.ignore import load_ignore_patterns
from second_brain.indexer import build_graph, iter_files
from second_brain.model import Graph, NodeType

_CHUNK = 65536
# Above this size a text file is hashed raw instead of normalized: it bounds memory, and a
# CRLF flip on a huge file then reads as "changed" - a SAFE false positive for the gate
# (it never hides a real change), unlike loading a multi-hundred-MB file into RAM.
_NORMALIZE_CAP = 8_000_000

# Files hashed with normalized line endings (CRLF/CR -> LF) to avoid cross-platform churn.
_TEXT_HASH_EXTS = {
    ".md", ".markdown", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".html",
    ".htm", ".css", ".sql", ".ps1", ".psm1", ".sh", ".bash", ".go", ".rs", ".java", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".cs",
}
# Content-hash text source/docs up to this size; data, binaries and larger files use a cheap
# size+mtime signature instead (no bytes read) so indexing stays light on data-heavy projects.
_CONTENT_HASH_CAP = 1_000_000


__all__ = ["file_hash", "build_manifest", "index", "diff_manifest", "fast_signature",
           "is_stale", "auto_refresh_enabled", "load_or_refresh"]


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def file_hash(path: Path, *, normalize_newlines: bool = False) -> str:
    """Return a short, stable content hash of a file.

    With ``normalize_newlines`` the bytes are read whole and CRLF/CR collapsed to LF before
    hashing (correct across chunk boundaries); otherwise the file is streamed in chunks.
    """
    h = hashlib.blake2b(digest_size=16)
    if normalize_newlines and path.stat().st_size <= _NORMALIZE_CAP:
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        h.update(data)
    else:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
    return h.hexdigest()


def _hash_rel(root: Path, rel: str) -> str | None:
    """Freshness signature for a file.

    Source/doc/config text up to ``_CONTENT_HASH_CAP`` is content-hashed with newline
    normalization (precise and cross-platform stable). Data, binaries and large files use a cheap
    ``size+mtime`` signature - no bytes are read - so indexing stays fast on data-heavy projects.
    """
    p = root / rel
    try:
        st = p.stat()
    except OSError:
        return None
    if _ext(rel) in _TEXT_HASH_EXTS and st.st_size <= _CONTENT_HASH_CAP:
        try:
            return file_hash(p, normalize_newlines=True)
        except OSError:
            return None
    return f"s{st.st_size}:m{int(st.st_mtime)}"


def build_manifest(root: str | os.PathLike[str]) -> dict[str, str]:
    """Return ``{relative_path: hash}`` for every indexable file under ``root``."""
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p))
    out: dict[str, str] = {}
    for rel in rels:
        hv = _hash_rel(root_p, rel)
        if hv is not None:
            out[rel] = hv
    return out


def index(
    root: str | os.PathLike[str], *, operational: bool = True, symbols: bool = False
) -> tuple[Graph, dict[str, str]]:
    """Build the graph and the manifest from one directory walk.

    The filesystem is enumerated once (``iter_files``); file *contents* are still read again to
    hash them for the manifest, so this is not zero double-I/O - just a single directory listing
    shared by graph build and manifest. ``symbols=True`` adds the opt-in symbol/call layer.
    """
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p))
    graph = build_graph(root_p, symbols=symbols, _rels=rels)
    if operational:
        from second_brain.operational import enrich
        enrich(graph, root_p)
    manifest: dict[str, str] = {}
    for rel in rels:
        hv = _hash_rel(root_p, rel)
        if hv is not None:
            manifest[rel] = hv
    return graph, manifest


def diff_manifest(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """Return ``{added, removed, changed}`` between two manifests (sorted lists)."""
    old_k, new_k = set(old), set(new)
    return {
        "added": sorted(new_k - old_k),
        "removed": sorted(old_k - new_k),
        "changed": sorted(k for k in (old_k & new_k) if old[k] != new[k]),
    }


# -- self-refreshing reads ---------------------------------------------------------------------
# A query should never answer from a stale map. Instead of re-hashing every file on each query
# (expensive on big repos), we keep a cheap signature — size+mtime per file, stat() only, no
# bytes read — and rebuild only when it differs. This makes "always fresh" the default behavior
# of the tool itself, with no external scheduler and no dependencies.

_OFF_VALUES = {"0", "false", "no", "off"}
# Throttle: in a long-running server, re-stat'ing every file on every query costs O(files).
# With SECOND_BRAIN_REFRESH_TTL=<seconds> the staleness check is skipped if it ran within that
# window for the same project. Default 0 = always check (freshness-first). Per-repo graphs (the
# recommended layout) keep the check cheap; raise the TTL only for a huge single monorepo graph.
_LAST_CHECK: dict[str, float] = {}


def fast_signature(root: str | os.PathLike[str]) -> dict[str, str]:
    """Cheap per-file signature ``{relpath: "size:mtime_ns"}`` using stat only (no file reads).

    ``st_mtime_ns`` (nanoseconds) is used rather than whole seconds so an edit made shortly after
    a build is still detected; the only blind spot is a same-size edit within the *same filesystem
    tick* as the build (a real but very narrow window — ``second-brain gate``'s content-hash check
    catches it exactly).
    """
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p))
    out: dict[str, str] = {}
    for rel in rels:
        try:
            st = (root_p / rel).stat()
        except OSError:
            continue
        out[rel] = f"{st.st_size}:{st.st_mtime_ns}"
    return out


def is_stale(root: str | os.PathLike[str]) -> bool:
    """True if the project changed since the stored signature (or there is no signature yet)."""
    from second_brain import store
    old = store.load_signature(root)
    if old is None:
        return True  # no baseline -> rebuild once (which writes the signature)
    return old != fast_signature(root)


def auto_refresh_enabled() -> bool:
    """Whether self-refreshing reads are on (env ``SECOND_BRAIN_AUTO_REFRESH``, default on)."""
    return os.environ.get("SECOND_BRAIN_AUTO_REFRESH", "1").strip().lower() not in _OFF_VALUES


def _refresh_ttl() -> float:
    try:
        ttl = float(os.environ.get("SECOND_BRAIN_REFRESH_TTL", "150"))
    except ValueError:
        return 0.0
    return max(0.0, ttl) if math.isfinite(ttl) else 0.0  # inf/nan -> always check (never freeze)


def _should_check(root: str | os.PathLike[str]) -> bool:
    """Throttle the staleness check to at most once per TTL window per project (if TTL > 0)."""
    ttl = _refresh_ttl()
    if ttl <= 0:
        return True
    key = str(Path(root).resolve())
    now = time.monotonic()
    last = _LAST_CHECK.get(key)
    if last is not None and (now - last) < ttl:
        return False
    _LAST_CHECK[key] = now
    return True


def _has_symbols(graph: Graph) -> bool:
    return any(n.type is NodeType.SYMBOL for n in graph.nodes.values())


def _save_quiet(
    root: str | os.PathLike[str], g: Graph, m: dict[str, str], *,
    symbols: bool, signature: dict[str, str],
) -> None:
    """Persist the store, ignoring write errors (read-only checkout / locked store)."""
    from second_brain import store
    try:
        store.save(root, g, m, signature=signature, symbols=symbols)
    except OSError:
        pass  # degrade gracefully: the in-memory graph is still served


def load_or_refresh(
    root: str | os.PathLike[str], *, refresh: bool | None = None
) -> Graph:
    """Return the project graph, rebuilt **iff** the project changed since the last build.

    This is the read path for every query: it auto-builds on first touch and silently refreshes
    a stale store before answering, so an assistant always sees the current project — including
    *uncommitted* edits — without a manual rebuild. The staleness check is a stat-only signature
    diff (cheap). Set ``refresh=False`` (or env ``SECOND_BRAIN_AUTO_REFRESH=0``) to serve the
    stored graph as-is; ``SECOND_BRAIN_REFRESH_TTL=<seconds>`` throttles the check on huge graphs.
    The rebuild preserves the stored mode (file-level or ``--symbols``), and a store write that
    fails (read-only checkout) degrades to serving the in-memory graph instead of crashing.
    """
    from second_brain import store
    if refresh is None:
        refresh = auto_refresh_enabled()

    g = store.load_graph(root)
    if g is None:  # first touch: build + persist (graph, manifest, signature, mode)
        # Capture the signature BEFORE reading file contents: if a file changes during the walk,
        # the stored signature is then "older" than the change, so the next query sees a mismatch
        # and rebuilds (false-stale = safe) — instead of a permanent false-fresh.
        sig = fast_signature(root)
        built, m = index(root)
        _save_quiet(root, built, m, symbols=False, signature=sig)
        return built
    if refresh and _should_check(root) and is_stale(root):
        # Prefer the persisted build mode; fall back to "are there symbol nodes?" only if the
        # store predates mode.json (so a --symbols build of a then-symbol-less tree is preserved).
        mode = store.load_symbols_mode(root)
        use_symbols = mode if mode is not None else _has_symbols(g)
        sig = fast_signature(root)  # before the walk (see first-touch note)
        try:
            rebuilt, m = index(root, symbols=use_symbols)
        except Exception:
            return g  # any rebuild failure -> serve the loaded graph (stale but alive), never crash
        _save_quiet(root, rebuilt, m, symbols=use_symbols, signature=sig)
        return rebuilt
    return g
