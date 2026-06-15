"""Persist the derived graph and manifest under ``<project>/.secondbrain/``.

The files are derived and regenerable; they never replace the project's own sources.
Writes are atomic (temp file + ``os.replace``) so a crash can't leave a half-written graph.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from second_brain.model import Graph

STORE_DIRNAME = ".secondbrain"


def store_dir(root: str | os.PathLike[str]) -> Path:
    return Path(root).resolve() / STORE_DIRNAME


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
) -> Path:
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    _atomic_write(d / "graph.json", graph.to_json())
    _atomic_write(
        d / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
    )
    # Optional cheap freshness signature (size+mtime per file) — lets queries detect "did
    # anything change?" with stat() only (no hashing), powering self-refreshing reads.
    if signature is not None:
        _atomic_write(
            d / "signature.json",
            json.dumps(signature, ensure_ascii=False, indent=2, sort_keys=True),
        )
    return d


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


def load_graph(root: str | os.PathLike[str]) -> Graph | None:
    """Load the stored graph, or ``None`` if missing or corrupt (so callers degrade)."""
    p = store_dir(root) / "graph.json"
    if not p.is_file():
        return None
    try:
        return Graph.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


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
