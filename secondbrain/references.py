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

_MD_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?\s*(?:\"[^\"]*\"|'[^']*')?\s*\)")
_WIKILINK_RE = re.compile(r"\[\[\s*([^\]|#]+?)\s*(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")

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

    for m in _MD_LINK_RE.finditer(text):
        _add(m.group(1), "link")
    for m in _WIKILINK_RE.finditer(text):
        _add(m.group(1), "wikilink")
    for m in _PATH_RE.finditer(text):
        _add(m.group(1), "path")

    return found


def extract_references(text: str) -> list[str]:
    """Return de-duplicated reference targets in first-seen order (URLs excluded)."""
    return [t for t, _ in extract_references_tagged(text)]
