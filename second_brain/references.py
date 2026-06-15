"""Extract documentation references from text.

Three kinds, because real projects use all three:
- Markdown links ``[label](target)``
- Wikilinks ``[[Name]]`` / ``[[Name|alias]]``
- **Plain path mentions in prose** (e.g. ``src/app.py`` written inside a sentence) — the
  part standard tools miss, and the reason Second Brain exists for documentation.

Returned targets are raw strings (anchors/whitespace stripped, URLs skipped); resolving
them to actual project files is the indexer's job.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://|^mailto:", re.IGNORECASE)

# A link target never contains ']' (and excluding it makes a pathological run of unclosed `](`
# fail fast — no backtracking, so no ReDoS). The length cap is defense-in-depth, mirroring the
# wikilink/inline-code regexes below.
_MD_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>\]]{1,2000})>?\s*(?:\"[^\"]*\"|'[^']*')?\s*\)")
# Bounded + single-line: a wikilink name/anchor/alias is short and never spans a newline.
# The length caps and `\n` exclusion keep matching linear even on a pathological document full
# of unclosed `[[` (no quadratic backtracking on large files).
_WIKILINK_RE = re.compile(
    r"\[\[\s*([^\]|#\n]{1,200}?)\s*(?:#[^\]|\n]{0,200})?(?:\|[^\]\n]{0,200})?\]\]"
)

# Path-like token ending in a known project extension.
_REF_EXTS = (
    "md|markdown|rst|txt|pdf|html|htm|docx|pptx|odt|"
    "py|js|ts|tsx|jsx|mjs|cjs|go|rs|java|c|cc|cpp|h|hpp|rb|php|cs|"
    "ps1|psm1|sh|bash|sql|vcl|"
    "toml|ini|cfg|conf|yaml|yml|json|jsonl|xml|csv|tsv|db|sqlite|duckdb|parquet"
)
_PATH_RE = re.compile(
    r"(?<![\w./\\-])([A-Za-z0-9_][A-Za-z0-9_\-./\\]*\.(?:" + _REF_EXTS + r"))\b"
)

# Code spans: fenced blocks ``` ``` / ~~~ ~~~ and inline `code`. Documentation that SHOWS
# link/wikilink SYNTAX as an example (e.g. `[label](target)`) must NOT become a real link.
# Stripped only for link/wikilink extraction; path-in-prose still runs on the full text,
# because file paths written in backticks (e.g. `src/app.py`) ARE genuine references — the
# core thing Second Brain is meant to catch. (Regression 2026-06-14: graph-format.md -> target.)
#
# Inline code follows the CommonMark rule: an opening run of N backticks is closed by the next
# run of exactly N backticks, and inner backticks are literal. So a doc that shows a single-
# backtick example inside a double-backtick span — `` `[label](target)` `` — keeps the inner
# `[label](target)` as code, not a link. A plain `+[^`\n]*`+ regex mispairs those delimiters
# and leaks the inner link; the backreference pairs equal-length runs. Bounded length keeps it
# from backtracking pathologically on a line full of stray backticks.
_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`+)[^\n]{0,2000}?\1")


def _blank_code(text: str) -> str:
    """Replace code spans with spaces of equal length (offsets/lines stay stable)."""
    text = _FENCE_RE.sub(lambda m: " " * len(m.group(0)), text)
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _clean(target: str) -> str:
    t = target.strip().strip("`").strip()
    # Drop anchors and query strings.
    for sep in ("#", "?"):
        if sep in t:
            t = t.split(sep, 1)[0]
    return t.replace("\\", "/").strip()


def extract_references_tagged(text: str) -> list[tuple[str, str]]:
    """Return de-duplicated ``(target, kind)`` in first-seen order (URLs excluded).

    ``kind`` is ``"link"`` (markdown link), ``"wikilink"``, or ``"path"`` (plain mention).
    The kind matters downstream: links/wikilinks are intentional and may be reported as
    broken; a plain prose mention is only used when it resolves (otherwise it is noise like
    a library name or an example).
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(raw: str, kind: str) -> None:
        if _URL_RE.match(raw.strip()):
            return
        t = _clean(raw)
        if not t or t in seen:
            return
        seen.add(t)
        found.append((t, kind))

    # Links/wikilinks: skip code spans (example syntax in `code` is not a real link).
    # Paths: full text (a file path in backticks is a genuine prose reference).
    no_code = _blank_code(text)
    for m in _MD_LINK_RE.finditer(no_code):
        _add(m.group(1), "link")
    for m in _WIKILINK_RE.finditer(no_code):
        _add(m.group(1), "wikilink")
    for m in _PATH_RE.finditer(text):
        _add(m.group(1), "path")

    return found


def extract_references(text: str) -> list[str]:
    """Return de-duplicated reference targets in first-seen order (URLs excluded)."""
    return [t for t, _ in extract_references_tagged(text)]
