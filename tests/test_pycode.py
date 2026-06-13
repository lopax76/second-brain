"""Import extraction tests — pycode is the sole source of all import edges."""

from __future__ import annotations

from secondbrain.pycode import js_imports, python_imports


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
