"""Symbol-level call graph for a single Python file, via ``ast`` (stdlib, zero-dep).

Extracts the functions/classes a file *defines* and the calls *between them within the same
file*. Resolution is deliberately **conservative** — it only records a call edge when the target
is unambiguous — to avoid the classic name-based call-graph mistakes:

- ``self.save()`` resolves to the method of the *enclosing class*, never to some unrelated
  same-file ``save`` (no receiver-blind same-file false positives);
- a class does **not** inherit the calls made by its methods (the caller is the method, not the
  class — no double counting);
- a bare ``f()`` links only when ``f`` is a *unique* module-level def/class in this file;
- attribute calls on anything other than ``self`` (``x.foo()``, ``mod.bar()``) are skipped — we
  do no type inference, so cross-file/receiver calls are left to the file-level ``imports`` edges
  rather than guessed (a safe false negative, not a wrong edge).

So the graph gains symbol nodes + intra-file call structure with no spurious edges; cross-file
dependency stays represented at file granularity by the existing ``imports`` edges.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

_FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Def:
    """A defined symbol with its dotted qualified name (e.g. ``Server.start``)."""

    qualname: str
    kind: str  # "def" | "async def" | "class"
    line: int


def _kind(node: ast.AST) -> str:
    if isinstance(node, ast.AsyncFunctionDef):
        return "async def"
    if isinstance(node, ast.ClassDef):
        return "class"
    return "def"


def extract(source: str) -> tuple[list[Def], list[tuple[str, str]]]:
    """Return ``(defs, calls)`` for one Python source.

    ``defs`` are all functions/classes (nested included) in source order; ``calls`` is a
    de-duplicated list of ``(caller_qualname, callee_qualname)`` resolved within this file.
    A syntax error yields ``([], [])``.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return [], []

    defs: list[Def] = []
    top_level: dict[str, str | None] = {}     # module-level name -> qualname (None if ambiguous)
    # (class_qualname, method) -> qualname. Keyed by the class's FULL dotted qualname so a nested
    # class A.B never collides with a top-level class B (would mis-resolve self.m()).
    methods: dict[tuple[str, str], str] = {}

    # Pass 1: collect definitions and the resolution tables. ``class_qual`` is the dotted name of
    # the class whose body we are directly in (None at module level / inside a function), so only
    # real methods (direct children of a class) register in ``methods``.
    def collect(body: list[ast.stmt], stack: list[str], class_qual: str | None) -> None:
        for n in body:
            if isinstance(n, _FuncDef | ast.ClassDef):
                qual = ".".join(stack + [n.name])
                defs.append(Def(qual, _kind(n), n.lineno))
                if not stack:
                    top_level[n.name] = None if n.name in top_level else qual
                elif class_qual is not None and isinstance(n, _FuncDef):
                    methods[(class_qual, n.name)] = qual
                inner_class = qual if isinstance(n, ast.ClassDef) else None
                collect(n.body, stack + [n.name], inner_class)

    collect(tree.body, [], None)

    # Pass 2: resolve calls, attributing each to its nearest enclosing function symbol.
    calls: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _record(call: ast.Call, caller: str | None, klass: str | None) -> None:
        if caller is None:  # a call at module/class-body level has no symbol caller
            return
        f = call.func
        target: str | None = None
        if isinstance(f, ast.Name):
            target = top_level.get(f.id)  # unique module-level def/class, else None
        elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
              and f.value.id == "self" and klass is not None):
            target = methods.get((klass, f.attr))
        if target and (caller, target) not in seen:
            seen.add((caller, target))
            calls.append((caller, target))

    def walk(node: ast.AST, caller: str | None, klass: str | None, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                # Entering a class body: caller resets (class-body calls have no symbol caller),
                # class context becomes this class's FULL qualname (matches the methods table key,
                # so a nested A.B does not borrow a top-level B's methods).
                walk(child, None, ".".join(stack + [child.name]), stack + [child.name])
            elif isinstance(child, _FuncDef):
                qual = ".".join(stack + [child.name])
                walk(child, qual, klass, stack + [child.name])
            else:
                if isinstance(child, ast.Call):
                    _record(child, caller, klass)
                walk(child, caller, klass, stack)

    walk(tree, None, None, [])
    return defs, calls


__all__ = ["Def", "extract"]
