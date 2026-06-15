"""Tests for the conservative same-file Python call graph."""

from __future__ import annotations

from second_brain.pysymbols import extract

SRC = '''\
def helper():
    return 1


def runner():
    helper()      # bare, unique -> edge
    other()       # ambiguous (defined twice) -> no edge


def other():
    pass


def other():      # duplicate top-level name -> ambiguous
    pass


class Server:
    def start(self):
        self.stop()      # self -> Server.stop
        helper()         # bare unique -> helper
        x.foo()          # attribute on non-self -> no edge
        self.missing()   # undefined method -> no edge

    def stop(self):
        pass
'''


def _defs_calls():
    defs, calls = extract(SRC)
    return {d.qualname for d in defs}, set(calls)


def test_defs_include_methods_qualnames():
    names, _ = _defs_calls()
    assert {"helper", "runner", "Server", "Server.start", "Server.stop"} <= names


def test_self_call_resolves_to_enclosing_class_method():
    _, calls = _defs_calls()
    assert ("Server.start", "Server.stop") in calls


def test_bare_unique_call_resolves():
    _, calls = _defs_calls()
    assert ("runner", "helper") in calls
    assert ("Server.start", "helper") in calls


def test_ambiguous_bare_name_not_linked():
    _, calls = _defs_calls()
    assert all(callee != "other" for _, callee in calls)


def test_non_self_attribute_call_not_linked():
    _, calls = _defs_calls()
    # x.foo() and self.missing() must not create edges
    assert ("Server.start", "x.foo") not in calls
    assert all(callee != "foo" and callee != "missing" for _, callee in calls)


def test_class_does_not_inherit_method_calls():
    _, calls = _defs_calls()
    # the caller is always a function/method, never the class itself
    assert all(caller != "Server" for caller, _ in calls)


def test_nested_class_homonym_does_not_borrow_top_level_method():
    # Regression: a nested class A.B calling self.m() must NOT link to a top-level B.m
    # (the dotted class qualname keys the methods table, so A.B != B).
    src = (
        "class B:\n"
        "    def m(self):\n"
        "        pass\n\n\n"
        "class A:\n"
        "    class B:\n"
        "        def caller(self):\n"
        "            self.m()   # A.B has no m -> no edge\n"
    )
    _, calls = extract(src)
    assert ("A.B.caller", "B.m") not in calls
    assert all(callee != "B.m" for _, callee in calls)


def test_nested_class_self_resolves_within_its_own_class():
    # Bonus from the fix: a method in a nested class can resolve self.<sibling method>.
    src = (
        "class A:\n"
        "    class B:\n"
        "        def caller(self):\n"
        "            self.helper()\n"
        "        def helper(self):\n"
        "            pass\n"
    )
    _, calls = extract(src)
    assert ("A.B.caller", "A.B.helper") in calls


def test_async_def_extracted_and_calls_resolve():
    defs, calls = extract("async def fetch():\n    helper()\n\n\ndef helper():\n    pass\n")
    names = {d.qualname for d in defs}
    kinds = {d.qualname: d.kind for d in defs}
    assert {"fetch", "helper"} <= names
    assert kinds["fetch"] == "async def"
    assert ("fetch", "helper") in calls


def test_syntax_error_returns_empty():
    assert extract("def (:\n") == ([], [])
