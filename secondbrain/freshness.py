"""Content-hash freshness + the single-walk ``index`` entry point.

Hashing uses the standard-library BLAKE2b (fast, no dependency). For text files the hash is
computed on newline-normalized bytes so a CRLF<->LF flip (e.g. a git checkout on Windows)
does not look like a content change. The manifest is a small ``{relative_path: hash}`` map
stored next to the graph; diffing it against the current files tells the gate whether the
brain is still in sync with the project.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from secondbrain.ignore import load_ignore_patterns
from secondbrain.indexer import build_graph, iter_files
from secondbrain.model import Graph

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
    root: str | os.PathLike[str], *, operational: bool = True
) -> tuple[Graph, dict[str, str]]:
    """Build the graph and the manifest from one directory walk.

    The filesystem is enumerated once (``iter_files``); file *contents* are still read again to
    hash them for the manifest, so this is not zero double-I/O - just a single directory listing
    shared by graph build and manifest.
    """
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p))
    graph = build_graph(root_p, _rels=rels)
    if operational:
        from secondbrain.operational import enrich
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
