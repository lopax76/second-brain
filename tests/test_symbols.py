"""Tests for the Python symbol layer (v0.2)."""

from __future__ import annotations

from second_brain.symbols import extract_symbols, render

SRC = '''\
import os


def top(a: int, b: str = "x") -> bool:
    def inner(z):
        return z
    return True


async def fetch(url: str) -> None:
    ...


class Server(Base, metaclass=Meta):
    def start(self, port: int = 8000) -> None:
        ...
'''


def test_extracts_functions_classes_nested():
    names = [(s.kind, s.name, s.depth) for s in extract_symbols(SRC)]
    assert ("def", "top", 0) in names
    assert ("def", "inner", 1) in names  # nested function
    assert ("async def", "fetch", 0) in names
    assert ("class", "Server", 0) in names
    assert ("def", "start", 1) in names  # method


def test_signatures_include_annotations_and_defaults():
    sig = {s.name: s.signature for s in extract_symbols(SRC)}
    assert sig["top"].startswith("def top(")
    assert "a: int" in sig["top"] and "b: str" in sig["top"] and "'x'" in sig["top"]
    assert sig["top"].endswith("-> bool")
    assert sig["fetch"] == "async def fetch(url: str) -> None"
    assert sig["Server"].startswith("class Server(Base")


def test_order_and_line_numbers():
    syms = extract_symbols(SRC)
    assert [s.name for s in syms] == ["top", "inner", "fetch", "Server", "start"]
    assert syms[0].line == 4  # def top is on line 4


def test_syntax_error_returns_empty():
    assert extract_symbols("def (:\n") == []


def test_render():
    out = render("a.py", extract_symbols(SRC))
    assert out.startswith("a.py")
    assert "def top(" in out and "[L4]" in out
    assert render("e.py", []) == "e.py\n  (no functions or classes)"
