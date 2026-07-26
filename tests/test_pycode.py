"""Import extraction tests — pycode is the sole source of all import edges."""

from __future__ import annotations

import ast

import pytest

from second_brain.pycode import PyImport, js_imports, python_imports


def _walk_imports(source: str) -> list[PyImport]:
    """Reference implementation: collect imports with ``ast.walk``, visiting every node.

    ``python_imports`` deliberately visits only the fields that can hold statements, which is far
    cheaper — but its correctness then rests entirely on that list of field names being complete.
    Comparing against a full walk is what turns that assumption into something the suite checks,
    including for a statement field added by a future version of Python.
    """
    tree = ast.parse(source)
    out: list[PyImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(PyImport(level=0, module=alias.name, names=()))
        elif isinstance(node, ast.ImportFrom):
            out.append(
                PyImport(level=node.level or 0, module=node.module,
                         names=tuple(a.name for a in node.names))
            )
    return out


# Every construct that nests statements — one per field python_imports walks, plus the shapes
# where a forgotten field silently loses edges instead of raising.
_NESTED_SOURCES = [
    # match / case — the field ("cases") whose loss is completely silent
    "match x:\n"
    "    case 1:\n"
    "        import json\n"
    "    case _:\n"
    "        from . import helper\n",
    "match x:\n"
    "    case [1, *rest] if rest:\n"
    "        import os\n"
    "    case {'k': v}:\n"
    "        import re\n",
    "match x:\n"
    "    case 1:\n"
    "        match y:\n"
    "            case 2:\n"
    "                import csv\n",
    # try / except* / else / finally — body, handlers, orelse, finalbody
    "try:\n"
    "    import a\n"
    "except* TypeError:\n"
    "    import b\n",
    "try:\n"
    "    import a\n"
    "except ValueError:\n"
    "    import b\n"
    "else:\n"
    "    import c\n"
    "finally:\n"
    "    import d\n",
    # async variants
    "async def f():\n"
    "    async with x:\n"
    "        import a\n"
    "    async for i in y:\n"
    "        import b\n",
    # loops with else
    "for i in y:\n    import a\nelse:\n    import b\n",
    "while x:\n    import a\nelse:\n    from .. import b, c\n",
    "with open('f') as f, open('g') as g:\n    import a\n",
    # nesting through class and function bodies
    "def outer():\n"
    "    class Inner:\n"
    "        import a\n"
    "        def m(self):\n"
    "            from . import b\n",
    "if x:\n    import a\nelif y:\n    import b\nelse:\n    import c\n",
    "class C:\n    if x:\n        import a\n    else:\n        from .p import q\n",
    # plain forms, and shapes that must yield nothing
    "import a, b, c\nfrom .x import y as z, w\nfrom ...pkg import *\n",
    "def f(cb=lambda: __import__('a')):\n    import b\n",
    "x = [i for i in range(3)]\n",
    "",
    "# only a comment\n",
]


@pytest.mark.parametrize("source", _NESTED_SOURCES)
def test_python_imports_matches_a_full_ast_walk(source: str) -> None:
    assert python_imports(source) == _walk_imports(source)


def test_imports_inside_match_case_are_found() -> None:
    # Spelled out separately: dropping "cases" from the statement fields loses these two silently,
    # and the whole file's import edges vanish without any error.
    src = "match x:\n    case 1:\n        import json\n    case _:\n        from . import helper\n"
    got = python_imports(src)
    assert PyImport(level=0, module="json", names=()) in got
    assert PyImport(level=1, module=None, names=("helper",)) in got


def test_js_imports_ignores_comments() -> None:
    src = "// import h from './helper'\nimport a from './real'\n/* import x from './blk' */\n"
    assert js_imports(src) == ["./real"]


def test_js_imports_dynamic_and_backtick() -> None:
    assert js_imports("const m = await import('./dyn')") == ["./dyn"]
    assert js_imports("import x from `./tmpl`") == ["./tmpl"]


def test_python_imports_absolute_and_aliases() -> None:
    imps = python_imports("import os\nimport a, b\n")
    mods = {(i.level, i.module) for i in imps}
    assert (0, "os") in mods
    assert (0, "a") in mods and (0, "b") in mods


def test_python_imports_from_relative() -> None:
    imps = python_imports("from . import x\nfrom ..pkg import y, z\n")
    rel = {(i.level, i.module, i.names) for i in imps}
    assert (1, None, ("x",)) in rel
    assert (2, "pkg", ("y", "z")) in rel


def test_python_imports_from_module() -> None:
    (imp,) = python_imports("from mod.sub import a, b\n")
    assert imp.level == 0 and imp.module == "mod.sub" and imp.names == ("a", "b")


def test_python_imports_syntax_error_is_empty() -> None:
    assert python_imports("def (:\n") == []


def test_js_imports_relative_only_and_deduped() -> None:
    src = (
        "import x from './a'\n"
        "export { y } from './b'\n"
        "const c = require('./c')\n"
        "import React from 'react'\n"  # bare specifier -> excluded
        "import again from './a'\n"  # duplicate -> deduped
    )
    assert js_imports(src) == ["./a", "./b", "./c"]
