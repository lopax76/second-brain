"""What the indexer skips: derived/vendor directories, noise files, and user patterns.

A project may add a ``.secondbrainignore`` file at its root with one glob pattern per line
(``#`` comments allowed). Patterns are matched against the POSIX relative path.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

# Directory names never walked into.
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn",
        ".secondbrain",
        "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache",
        ".venv", "venv", "env", "node_modules", "site-packages",
        "dist", "build", ".eggs", ".tox",
        ".idea", ".vscode",
        "graphify-out",
    }
)

# Exact file names skipped.
DEFAULT_IGNORE_FILES: frozenset[str] = frozenset(
    {".DS_Store", "Thumbs.db", ".secondbrainignore", ".secondbrain.json", "package-lock.json",
     "poetry.lock", "yarn.lock"}
)

# Binary / noise extensions skipped entirely (not useful as knowledge nodes).
DEFAULT_IGNORE_EXTS: frozenset[str] = frozenset(
    {
        ".pyc", ".pyo", ".pyd",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
        ".woff", ".woff2", ".ttf", ".eot",
        ".zip", ".gz", ".tar", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
        ".lock",
    }
)


def load_ignore_patterns(root: Path) -> list[str]:
    """Read user glob patterns from ``<root>/.secondbrainignore`` (may be empty)."""
    f = root / ".secondbrainignore"
    if not f.is_file():
        return []
    out: list[str] = []
    for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def is_ignored_dir(name: str) -> bool:
    return name in DEFAULT_IGNORE_DIRS or name.endswith(".egg-info")


def is_ignored_file(rel_posix: str, name: str, patterns: list[str]) -> bool:
    """True if a file should be skipped (default names/extensions or a user pattern)."""
    if name in DEFAULT_IGNORE_FILES:
        return True
    # splitext (not rsplit) so dotfiles like ".lock" are extensionless, consistent with the
    # rest of the codebase (classify/indexer) and not mis-classified by their leading dot.
    ext = os.path.splitext(name)[1].lower()
    if ext in DEFAULT_IGNORE_EXTS:
        return True
    for pat in patterns:
        # fnmatchcase (not fnmatch) so matching is case-sensitive and identical on Windows and
        # POSIX - otherwise the same .secondbrainignore would index a different set per platform.
        if fnmatch.fnmatchcase(rel_posix, pat) or fnmatch.fnmatchcase(name, pat):
            return True
    return False
