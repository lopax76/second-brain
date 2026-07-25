"""Per-project configuration: an optional ``.secondbrain.json`` at the project root that tunes the
classification taxonomy (keywords, foundation-doc names, decision-id prefixes).

Zero-dependency (stdlib ``json``, works on Python 3.10+) and **fail-safe**: a missing, unreadable
or malformed file yields the built-in defaults, so behaviour is byte-identical without a config.

Shape (every field optional)::

    {
      "classify": {
        "mode": "extend",                         // "extend" (default) | "replace"
        "structure_names": ["progetto.md"],       // extra foundation-doc names -> STRUCTURE
        "keywords": {
          "design": ["blueprint"],                // extra keywords -> DESIGN
          "report": ["collaudo"]                  // extra keywords -> REPORT
        },
        "decision_id_prefixes": ["DEC"]           // extra ADR/RFC-like ids -> decision nodes
      },
      "respect_gitignore": true                   // also skip files matched by the root .gitignore
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = ".secondbrain.json"


@dataclass(frozen=True)
class ClassifyConfig:
    """Parsed, validated classification overrides (empty = use defaults)."""

    mode: str = "extend"  # "extend" | "replace"
    structure_names: tuple[str, ...] = ()
    design_keywords: tuple[str, ...] = ()
    report_keywords: tuple[str, ...] = ()
    decision_id_prefixes: tuple[str, ...] = ()
    type_overrides: tuple[tuple[str, str], ...] = ()
    respect_gitignore: bool = False  # opt-in: also skip files matched by the root .gitignore


def _str_tuple(value: object) -> tuple[str, ...]:
    """Coerce a JSON value to a tuple of non-empty strings (anything else -> empty)."""
    if not isinstance(value, list):
        return ()
    return tuple(str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip())


def _type_overrides(value: object) -> tuple[tuple[str, str], ...]:
    """Coerce a JSON {path: type-name} mapping to normalized (posix-path, lower-name) pairs."""
    if not isinstance(value, dict):
        return ()
    out: list[tuple[str, str]] = []
    for k, v in value.items():
        if not (isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()):
            continue
        key = k.strip().replace("\\", "/")
        if key.startswith("./"):
            key = key[2:]
        key = key.lstrip("/")
        out.append((key, v.strip().lower()))
    return tuple(out)

def load_config(root: str | Path) -> ClassifyConfig:
    """Read ``<root>/.secondbrain.json`` and return its classification overrides.

    FAIL-SAFE: missing file, I/O error, or malformed JSON all return the empty default config
    (byte-identical to having no file at all).
    """
    path = Path(root) / CONFIG_NAME
    try:
        # utf-8-sig: strips a leading BOM if present, identical to utf-8 otherwise. Notepad and
        # PowerShell 5.1's Set-Content -Encoding utf8 both write a BOM, which made json.loads
        # raise and silently fall back to the defaults (so respect_gitignore stayed off).
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ClassifyConfig()
    if not isinstance(data, dict):
        return ClassifyConfig()
    # ``respect_gitignore`` is a top-level flag (not under "classify"); read it even when there is
    # no "classify" block, so a config with only {"respect_gitignore": true} still works.
    respect_gitignore = data.get("respect_gitignore") is True
    cls = data.get("classify")
    if not isinstance(cls, dict):
        return ClassifyConfig(respect_gitignore=respect_gitignore)
    kw = cls.get("keywords") if isinstance(cls.get("keywords"), dict) else {}
    mode = cls.get("mode")
    return ClassifyConfig(
        mode=mode if mode in ("extend", "replace") else "extend",
        structure_names=_str_tuple(cls.get("structure_names")),
        design_keywords=_str_tuple(kw.get("design")),
        report_keywords=_str_tuple(kw.get("report")),
        decision_id_prefixes=_str_tuple(cls.get("decision_id_prefixes")),
        type_overrides=_type_overrides(cls.get("type_overrides")),
        respect_gitignore=respect_gitignore,
    )


__all__ = ["CONFIG_NAME", "ClassifyConfig", "load_config"]
