"""Extract import edges from source code.

Python is parsed precisely with the standard-library ``ast`` (no third-party dependency).
JavaScript/TypeScript imports are matched best-effort with a regex and limited to relative
specifiers (the ones that point at project files). Resolution to actual files happens in the
indexer, which knows the full file/module map.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PyImport:
    """A single import statement, normalized for resolution.

    ``level`` is the relative-import depth (0 = absolute). ``module`` is the dotted module
    (may be ``None`` for ``from . import x``). ``names`` are the imported names (used when
    ``module`` is ``None`` to resolve sibling modules).
    """

    level: int
    module: str | None
    names: tuple[str, ...]


def python_imports(source: str) -> list[PyImport]:
    """Parse Python source and return its imports. Returns [] on syntax errors."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[PyImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(PyImport(level=0, module=alias.name, names=()))
        elif isinstance(node, ast.ImportFrom):
            names = tuple(a.name for a in node.names)
            out.append(PyImport(level=node.level or 0, module=node.module, names=names))
    return out


_JS_IMPORT_RE = re.compile(
    r"""(?:import\s[^'"]*?from\s*|import\s*|export\s[^'"]*?from\s*|require\(\s*)['"](\.[^'"]+)['"]""",
)


def js_imports(source: str) -> list[str]:
    """Return relative JS/TS import specifiers (starting with ``.``), best-effort."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _JS_IMPORT_RE.finditer(source):
        spec = m.group(1)
        if spec not in seen:
            seen.add(spec)
            out.append(spec)
    return out
