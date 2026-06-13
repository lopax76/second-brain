"""Classify a file into a NodeType from its path and name (heuristic, tunable).

The order of checks matters: more specific signals win. The classification is deliberately
conservative and documented; it is meant to be refined per project over time.
"""

from __future__ import annotations

import os
import re

from second_brain.model import NodeType

_PROGRAM_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".cs", ".swift", ".scala", ".lua",
    ".ps1", ".psm1", ".sh", ".bash", ".bat", ".cmd", ".sql", ".vcl", ".r",
}
_DATA_EXTS = {
    ".db", ".sqlite", ".sqlite3", ".duckdb", ".parquet", ".csv", ".tsv", ".jsonl", ".ndjson",
}
_CONFIG_EXTS = {
    ".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".env", ".json", ".xml", ".properties",
}
_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".pdf", ".html", ".htm", ".docx", ".pptx", ".odt"}

_STRUCTURE_NAMES = {
    "progetto.md", "progetto-storia.md", "readme.md", "readme", "index.md",
    "data-map.md", "changelog.md", "contributing.md", "license", "license.md",
    "license.txt", "authors", "notice",
}

_DECISION_RE = re.compile(r"(?i)(?:^|[-_/])(?:adr|decision|decisione|decisioni)(?:[-_/.]|$)")
_DESIGN_RE = re.compile(
    r"(?i)(?:^|[-_/])(?:disegno|design|piano|plan|roadmap|spec|blueprint|brief|"
    r"architettura|architecture)(?:[-_/.]|$)"
)
_REPORT_RE = re.compile(
    r"(?i)(?:^|[-_/])(?:report|rapporto|collaudo|diagnosi|revisione|readiness|analisi|analysis|audit|verifica|backtest|indagine|strumentazione)(?:[-_/.]|$)"
)
_DATE_RE = re.compile(r"(?<!\d)(?:20\d{2}[-_]?\d{2}[-_]?\d{2}|20\d{2}[-_]\d{2})(?!\d)")


def _ext(name: str) -> str:
    # os.path.splitext treats leading-dot names (".gitignore") as extensionless, which is
    # what we want (a dotfile has no "extension").
    return os.path.splitext(name)[1].lower()


def classify(rel_posix: str) -> NodeType:
    """Return the NodeType for a file given its POSIX relative path."""
    name = rel_posix.rsplit("/", 1)[-1]
    low = name.lower()
    ext = _ext(low)
    parts = [p.lower() for p in rel_posix.split("/")]

    # 1. Memory (path- or name-based)
    if "memory" in parts or low.startswith("memory.") or low == "memory.md":
        return NodeType.MEMORY

    # 2. Config / data / program by extension (strong signals)
    if ext in _DATA_EXTS:
        return NodeType.DATA
    if ext in _PROGRAM_EXTS:
        return NodeType.PROGRAM
    config_names = {".gitignore", ".secondbrainignore", "dockerfile", "caddyfile", "makefile"}
    if ext in _CONFIG_EXTS or low in config_names:
        return NodeType.CONFIG

    # 3. Foundation structure docs by name
    if low in _STRUCTURE_NAMES:
        return NodeType.STRUCTURE

    # 4. Document sub-typing by keyword / date (only for document-like files)
    if ext in _DOC_EXTS or ext == "":
        if _DECISION_RE.search(rel_posix):
            return NodeType.DECISION
        if _DESIGN_RE.search(rel_posix):
            return NodeType.DESIGN
        if _REPORT_RE.search(rel_posix) or _DATE_RE.search(name):
            return NodeType.REPORT
        # Fallback for loose documents: treat as project structure/knowledge.
        return NodeType.STRUCTURE

    # 5. Anything else (unknown extension) -> config-like by default.
    return NodeType.CONFIG
