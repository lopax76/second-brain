"""Persist the derived store under ``<project>/.secondbrain/``.

Five files: the graph, the content manifest, the cheap freshness signature, the build mode, and
the per-file extraction cache. All of them are derived and regenerable; they never replace the
project's own sources. Writes are atomic (temp file + ``os.replace``) so a crash can't leave a
half-written graph.

Each file being atomic is not the same as the *set* being coherent. Two builds running at once
interleave freely, and the surviving combination could be one build's graph next to another
build's manifest and signature — a store that describes the project correctly in every file that
gets checked, while the graph itself is stale. ``is_stale`` says fresh, ``gate`` says clean, and no
rebuild fixes it because nothing looks wrong. So ``save`` ends by writing a **stamp**: the digests
of the files it just wrote, together. A load verifies them, and a set that never came from a single
build fails to match and is refused — costing a rebuild instead of going quietly wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from second_brain.extract import CachedExtract, cache_from_json, cache_to_json
from second_brain.model import Graph

__all__ = ["STORE_DIRNAME", "store_dir", "save", "load_graph", "load_manifest",
           "load_signature", "load_symbols_mode", "load_extract", "is_coherent"]

STORE_DIRNAME = ".secondbrain"
STAMP_NAME = "stamp.json"

# The files whose disagreement produces a silently wrong answer: the graph is what gets served,
# and the manifest and signature are what `gate` and `is_stale` consult to decide it is fine.
# mode.json and extract.json are excluded on purpose — a mismatched build mode is harmless, and a
# mismatched extraction cache is already caught by its own per-file content keys.
_STAMPED = ("graph.json", "manifest.json", "signature.json")


def store_dir(root: str | os.PathLike[str]) -> Path:
    return Path(root).resolve() / STORE_DIRNAME


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save(
    root: str | os.PathLike[str],
    graph: Graph,
    manifest: dict[str, str],
    *,
    signature: dict[str, str] | None = None,
    symbols: bool | None = None,
    extract: dict[str, CachedExtract] | None = None,
) -> Path:
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    stamp: dict[str, str] = {}

    graph_text = graph.to_json()
    stamp["graph.json"] = _digest(graph_text)
    _atomic_write(d / "graph.json", graph_text)

    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    stamp["manifest.json"] = _digest(manifest_text)
    _atomic_write(d / "manifest.json", manifest_text)

    # Optional cheap freshness signature (size+mtime per file) — lets queries detect "did
    # anything change?" with stat() only (no hashing), powering self-refreshing reads.
    if signature is not None:
        signature_text = json.dumps(signature, ensure_ascii=False, indent=2, sort_keys=True)
        stamp["signature.json"] = _digest(signature_text)
        _atomic_write(d / "signature.json", signature_text)
    # Persist the build mode so a self-refresh rebuilds in the same mode even when the current
    # graph happens to contain zero symbol nodes (e.g. a --symbols build of a docs-only tree).
    if symbols is not None:
        _atomic_write(
            d / "mode.json", json.dumps({"symbols": bool(symbols)}, indent=2)
        )
    # Per-file raw extraction, keyed by a content digest up to the content-hash cap and by the
    # precise size+mtime_ns signature above it (see extract.py): the next build
    # re-reads only the files whose hash moved. Purely derived — deleting it costs one full
    # rebuild and nothing else. Written compactly (no indent): on a 20k-file tree the pretty
    # form is several MB of pure whitespace.
    if extract is not None:
        _atomic_write(
            d / "extract.json",
            json.dumps(cache_to_json(extract), ensure_ascii=False, separators=(",", ":")),
        )
    # LAST, always: the stamp binds the files above into one set. Written after them so a crash
    # leaves a stamp that does not match — refused on load, which is the safe direction.
    _atomic_write(d / STAMP_NAME, json.dumps(stamp, indent=2, sort_keys=True))
    return d


def is_coherent(root: str | os.PathLike[str]) -> bool:
    """True if the stamped files still match the stamp — i.e. they came from ONE build.

    A store written before stamps existed has none; it is accepted rather than thrown away, since
    absence of the stamp is not evidence of incoherence. The first save re-stamps it.
    """
    d = store_dir(root)
    p = d / STAMP_NAME
    if not p.is_file():
        return True
    try:
        stamp = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False  # a stamp we cannot read is not a stamp we can trust
    if not isinstance(stamp, dict):
        return False
    for name, expected in stamp.items():
        if name not in _STAMPED or not isinstance(expected, str):
            continue
        f = d / name
        if not f.is_file():
            return False  # stamped but gone
        try:
            if _digest(f.read_text(encoding="utf-8")) != expected:
                return False
        except OSError:
            return False
    return True


def load_extract(root: str | os.PathLike[str]) -> dict[str, CachedExtract]:
    """Load the per-file extraction cache; empty dict if missing, corrupt or from an old format."""
    p = store_dir(root) / "extract.json"
    if not p.is_file():
        return {}
    try:
        return cache_from_json(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, RecursionError):
        # RecursionError is a RuntimeError, NOT a ValueError: deeply nested JSON in the store made
        # it escape this guard and crash `build` on every run (only --full survived, because it
        # never loads the cache). The store is derived data — an unreadable one costs a rebuild.
        return {}


def load_signature(root: str | os.PathLike[str]) -> dict[str, str] | None:
    """Load the cheap freshness signature, or ``None`` if missing or corrupt."""
    p = store_dir(root) / "signature.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_symbols_mode(root: str | os.PathLike[str]) -> bool | None:
    """Load the persisted build mode (``symbols`` on/off), or ``None`` if unknown/corrupt."""
    p = store_dir(root) / "mode.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return bool(data.get("symbols")) if isinstance(data, dict) and "symbols" in data else None


def load_graph(root: str | os.PathLike[str]) -> Graph | None:
    """Load the stored graph, or ``None`` if missing, corrupt, or part of an incoherent store.

    The coherence check is here rather than at each call site because this is the single door every
    read path goes through: a store assembled from two overlapping builds is refused once, and every
    caller then behaves as it already does when there is no graph — it rebuilds.
    """
    p = store_dir(root) / "graph.json"
    if not p.is_file():
        return None
    if not is_coherent(root):
        return None
    try:
        return Graph.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None  # corrupt / non-dict JSON (e.g. a top-level array) -> degrade, don't crash


def load_manifest(root: str | os.PathLike[str]) -> dict[str, str] | None:
    """Load the stored manifest, or ``None`` if missing or corrupt."""
    p = store_dir(root) / "manifest.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
