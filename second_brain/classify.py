"""Classify a file into a NodeType from its path and name (heuristic, tunable).

The order of checks matters: more specific signals win. The keyword/name heuristics are English +
Italian by default and can be **extended or replaced per project** via ``.secondbrain.json`` (see
:mod:`second_brain.config`): build a :class:`ClassifyRules` with :func:`rules_from_config` and pass
it to :func:`classify`. With no config the behaviour is unchanged.

``NodeType.DECISION`` is **not** assigned here: it is reserved for decision IDENTIFIER nodes
(``D-XXX`` / ``ADR-N`` / ``RFC-N``) created by ``operational.add_decisions`` from document text. A
file is a document that may *define* a decision, so ADR/decision files classify as DESIGN.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from second_brain.config import ClassifyConfig
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
_CONFIG_NAMES = {".gitignore", ".secondbrainignore", "dockerfile", "caddyfile", "makefile"}

# Generic, de-personalized defaults (project-specific names like "progetto.md" belong in a
# per-project .secondbrain.json, not in the tool's built-in taxonomy).
_DEFAULT_STRUCTURE_NAMES = frozenset({
    "readme.md", "readme", "index.md", "changelog.md", "contributing.md",
    "license", "license.md", "license.txt", "authors", "notice",
})
_DEFAULT_DESIGN_KW: tuple[str, ...] = (
    "disegno", "design", "piano", "plan", "roadmap", "spec", "blueprint", "brief",
    "architettura", "architecture", "adr", "decision", "decisione", "decisioni",
)
_DEFAULT_REPORT_KW: tuple[str, ...] = (
    "report", "rapporto", "collaudo", "diagnosi", "revisione", "readiness", "analisi",
    "analysis", "audit", "verifica", "backtest", "indagine", "strumentazione",
)
_DATE_RE = re.compile(r"(?<!\d)(?:20\d{2}[-_]?\d{2}[-_]?\d{2}|20\d{2}[-_]\d{2})(?!\d)")


def _kw_re(words: tuple[str, ...]) -> re.Pattern[str]:
    """Boundary-anchored, case-insensitive alternation over path segments. Empty -> never match.

    An optional trailing ``s`` lets a singular keyword also match the regular English plural folder
    name (``design`` -> ``designs/``, ``report`` -> ``reports/``) without matching ``designer``
    (no separator after the ``s``).
    """
    body = "|".join(re.escape(w) for w in words) if words else r"(?!x)x"
    return re.compile(r"(?i)(?:^|[-_/])(?:" + body + r")s?(?:[-_/.]|$)")


@dataclass(frozen=True)
class ClassifyRules:
    """Compiled classification taxonomy (foundation-doc names + design/report matchers)."""

    structure_names: frozenset[str]
    design_re: re.Pattern[str]
    report_re: re.Pattern[str]


def default_rules() -> ClassifyRules:
    return ClassifyRules(
        structure_names=_DEFAULT_STRUCTURE_NAMES,
        design_re=_kw_re(_DEFAULT_DESIGN_KW),
        report_re=_kw_re(_DEFAULT_REPORT_KW),
    )


_DEFAULT_RULES = default_rules()


def rules_from_config(cfg: ClassifyConfig | None) -> ClassifyRules:
    """Build :class:`ClassifyRules` from a :class:`ClassifyConfig`.

    ``extend`` (default) adds the config's values to the built-in defaults; ``replace`` uses only
    the config's values, falling back to the defaults for any list left empty.
    """
    if cfg is None or (
        not cfg.structure_names and not cfg.design_keywords and not cfg.report_keywords
    ):
        return _DEFAULT_RULES
    extra_names = frozenset(n.lower() for n in cfg.structure_names)
    if cfg.mode == "replace":
        names = extra_names or _DEFAULT_STRUCTURE_NAMES
        design = cfg.design_keywords or _DEFAULT_DESIGN_KW
        report = cfg.report_keywords or _DEFAULT_REPORT_KW
    else:
        names = _DEFAULT_STRUCTURE_NAMES | extra_names
        design = _DEFAULT_DESIGN_KW + cfg.design_keywords
        report = _DEFAULT_REPORT_KW + cfg.report_keywords
    return ClassifyRules(structure_names=names, design_re=_kw_re(design), report_re=_kw_re(report))


def _ext(name: str) -> str:
    # os.path.splitext treats leading-dot names (".gitignore") as extensionless, which is
    # what we want (a dotfile has no "extension").
    return os.path.splitext(name)[1].lower()


def classify(rel_posix: str, rules: ClassifyRules | None = None) -> NodeType:
    """Return the NodeType for a POSIX relative path (using ``rules`` or the defaults)."""
    r = rules or _DEFAULT_RULES
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
    if ext in _CONFIG_EXTS or low in _CONFIG_NAMES:
        return NodeType.CONFIG

    # 3. Foundation structure docs by name
    if low in r.structure_names:
        return NodeType.STRUCTURE

    # 4. Document sub-typing by keyword / date (only for document-like files)
    if ext in _DOC_EXTS or ext == "":
        if r.design_re.search(rel_posix):
            return NodeType.DESIGN
        if r.report_re.search(rel_posix) or _DATE_RE.search(name):
            return NodeType.REPORT
        # Fallback for loose documents: treat as project structure/knowledge.
        return NodeType.STRUCTURE

    # 5. Anything else (unknown extension) -> config-like by default.
    return NodeType.CONFIG
