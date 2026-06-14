"""Symbol layer: function/class names + signatures from Python source via ``ast`` (stdlib).

Read-only and zero-dependency. Surfaced on demand by ``second-brain symbols <file>`` so an AI can
see signatures — which a file-level map omits and might otherwise hallucinate — WITHOUT bloating
the graph or the token budget: only the queried file is parsed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    """A top-level or nested function/class with its full signature."""

    kind: str  # "def" | "async def" | "class"
    name: str
    signature: str  # e.g. "def f(x: int = 0) -> bool" or "class Server(Base)"
    line: int
    depth: int  # 0 = top-level, 1 = method/nested, ...


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{kw} {node.name}({args}){ret}"


def _class_signature(node: ast.ClassDef) -> str:
    parts = [ast.unparse(b) for b in node.bases]
    parts += [f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords]
    bases = ", ".join(parts)
    return f"class {node.name}" + (f"({bases})" if bases else "")


def extract_symbols(source: str) -> list[Symbol]:
    """Return functions/classes (including nested) in source order. Syntax error -> empty list."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[Symbol] = []

    def visit(body: list[ast.stmt], depth: int) -> None:
        for n in body:
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                kind = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
                out.append(Symbol(kind, n.name, _func_signature(n), n.lineno, depth))
                visit(n.body, depth + 1)
            elif isinstance(n, ast.ClassDef):
                out.append(Symbol("class", n.name, _class_signature(n), n.lineno, depth))
                visit(n.body, depth + 1)

    visit(tree.body, 0)
    return out


def render(file_label: str, symbols: list[Symbol]) -> str:
    """Render a compact, indented listing for the CLI."""
    lines = [file_label]
    if not symbols:
        lines.append("  (no functions or classes)")
    for s in symbols:
        indent = "  " * (s.depth + 1)
        lines.append(f"{indent}{s.signature}   [L{s.line}]")
    return "\n".join(lines)


__all__ = ["Symbol", "extract_symbols", "render"]
