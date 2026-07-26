"""Extract import edges from source code.

Python is parsed precisely with the standard-library ``ast`` (no third-party dependency).
JavaScript/TypeScript imports are matched best-effort with a regex and limited to relative
specifiers (the ones that point at project files). Resolution to actual files happens in the
indexer, which knows the full file/module map.
"""

from __future__ import annotations

import ast
import re
from collections import deque
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


# Fields that hold nested *statements*. An import is a statement, so it can only ever appear as
# an element of one of these lists — never inside an expression. Walking just these skips the
# entire expression subtree, which is the bulk of a Python AST: measured on ~2.000 real Python
# files, import collection costs 3,3s with ``ast.walk`` against 2,1s here (of which 2,0s is
# ``ast.parse`` itself, unavoidable either way), and a full index of a 5.200-file Python tree
# drops from 11,1s to 6,9s. Fields are read in the node's own ``_fields`` order (not in the order
# of this tuple) so the breadth-first visit order — and therefore the resulting edge order — is
# identical to ``ast.walk``'s. That equivalence is not left to a comment: tests/test_pycode.py
# compares the two implementations directly on every statement-nesting construct.
_STMT_FIELDS = frozenset(("body", "orelse", "finalbody", "handlers", "cases"))


def python_imports(source: str) -> list[PyImport]:
    """Parse Python source and return its imports. Returns [] on syntax errors."""
    # Both forms of the statement contain the substring "import", so a source without it cannot
    # hold an Import/ImportFrom node — and parsing it would be pure waste. Exact, not heuristic.
    if "import" not in source:
        return []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[PyImport] = []
    queue: deque[ast.AST] = deque([tree])
    while queue:
        node = queue.popleft()
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(PyImport(level=0, module=alias.name, names=()))
            continue  # an import statement has no nested statements
        if isinstance(node, ast.ImportFrom):
            names = tuple(a.name for a in node.names)
            out.append(PyImport(level=node.level or 0, module=node.module, names=names))
            continue
        for fname in node._fields:
            if fname not in _STMT_FIELDS:
                continue
            children = getattr(node, fname, None)
            if children:
                queue.extend(c for c in children if isinstance(c, ast.AST))
    return out


# Matches static `import ... from '.x'`, bare `import '.x'`, dynamic `import('.x')`,
# `export ... from '.x'`, and `require('.x')`. Quote may be ' " or ` (static template). Only
# relative specifiers (starting with `.`) are captured — those that point at project files.
_JS_IMPORT_RE = re.compile(
    r"(?:import\s[^'\"`]*?from\s*|import\s*\(?\s*|export\s[^'\"`]*?from\s*|require\(\s*)"
    r"['\"`](\.[^'\"`]+)['\"`]",
)
# Strip comments first so an import mentioned in a comment isn't extracted as a real edge.
_JS_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def js_imports(source: str) -> list[str]:
    """Return relative JS/TS import specifiers (starting with ``.``), best-effort.

    Comments are stripped before matching, so a specifier written inside a ``//`` or ``/* */``
    comment does not produce a phantom import edge.
    """
    source = _JS_BLOCK_COMMENT_RE.sub(" ", source)
    source = _JS_LINE_COMMENT_RE.sub("", source)
    out: list[str] = []
    seen: set[str] = set()
    for m in _JS_IMPORT_RE.finditer(source):
        spec = m.group(1)
        if spec not in seen:
            seen.add(spec)
            out.append(spec)
    return out
