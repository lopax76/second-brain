"""What the indexer skips: derived/vendor directories, noise files, and user patterns.

A project may add a ``.secondbrainignore`` file at its root with one glob pattern per line
(``#`` comments allowed). Patterns are matched against the POSIX relative path.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
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


# -- optional .gitignore support (opt-in via .secondbrain.json "respect_gitignore": true) -------
# A pragmatic, deterministic subset of .gitignore semantics, applied to the ROOT .gitignore only:
# blank lines and "#" comments, glob (`*` `?` `[...]`-free), `**`, a leading "/" anchors to root,
# a trailing "/" matches directories only, and a leading "!" re-includes (negation). Last matching
# rule wins. NOT supported (documented): nested .gitignore files and rare escapes. Zero-dependency.

@dataclass(frozen=True)
class GitRule:
    """One compiled .gitignore line: a regex over the POSIX relative path + its flags."""

    regex: re.Pattern[str]
    negated: bool
    dir_only: bool


def _glob_to_regex(pat: str) -> str:
    """Translate a gitignore path glob (segment-aware) to a regex body (no anchors)."""
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        if pat[i:i + 3] == "**/":
            out.append("(?:.*/)?")  # any number of leading directories
            i += 3
        elif pat[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return "".join(out)


def _compile_gitignore_line(line: str) -> GitRule | None:
    """Compile one .gitignore line to a :class:`GitRule`, or ``None`` for blanks/comments."""
    s = line.rstrip("\n").rstrip()
    if not s or s.startswith("#"):
        return None
    negated = s.startswith("!")
    if negated:
        s = s[1:]
    if not s:
        return None
    dir_only = s.endswith("/")
    s = s.rstrip("/")
    if not s:
        return None
    anchored = s.startswith("/") or ("/" in s)  # a leading or embedded "/" anchors to root
    s = s.lstrip("/")
    body = _glob_to_regex(s)
    # Anchored: match the path from the root. Otherwise: match the basename at any depth. In both
    # cases also match everything *under* a matched directory (``(?:/.*)?``) so a dir rule like
    # ``build/`` excludes its contents even when tested file-by-file.
    prefix = "" if anchored else "(?:.*/)?"
    regex = re.compile("^" + prefix + body + "(?:/.*)?$")
    return GitRule(regex=regex, negated=negated, dir_only=dir_only)


def load_gitignore_rules(root: Path) -> list[GitRule]:
    """Read and compile the root ``.gitignore`` (in file order); empty if absent/unreadable."""
    f = root / ".gitignore"
    if not f.is_file():
        return []
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rules: list[GitRule] = []
    for line in text.splitlines():
        rule = _compile_gitignore_line(line)
        if rule is not None:
            rules.append(rule)
    return rules


def gitignored(rel_posix: str, is_dir: bool, rules: list[GitRule]) -> bool:
    """True if ``rel_posix`` is ignored by ``rules`` (last match wins; ``!`` re-includes)."""
    ignored = False
    for r in rules:
        if r.dir_only and not is_dir:
            continue
        if r.regex.match(rel_posix):
            ignored = not r.negated
    return ignored


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
