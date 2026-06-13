"""Tests for the ignore rules (default dirs/files/exts + user patterns)."""

from __future__ import annotations

from second_brain.ignore import is_ignored_dir, is_ignored_file


def test_default_extensions_and_names():
    assert is_ignored_file("a/b.pyc", "b.pyc", [])
    assert is_ignored_file("yarn.lock", "yarn.lock", [])
    assert not is_ignored_file("src/app.py", "app.py", [])


def test_dotfile_not_ignored_by_leading_dot():
    # ".lock" is a dotfile (extensionless via splitext), not the ignored ".lock" extension.
    assert not is_ignored_file(".lock", ".lock", [])
    assert not is_ignored_file(".gitignore", ".gitignore", [])


def test_user_patterns_match_path_or_name():
    assert is_ignored_file("build/x.txt", "x.txt", ["build/*"])
    assert is_ignored_file("notes.bak", "notes.bak", ["*.bak"])
    assert not is_ignored_file("src/app.py", "app.py", ["*.bak"])


def test_patterns_are_case_sensitive_cross_platform():
    # fnmatchcase: identical on Windows and POSIX - uppercase pattern must NOT match lowercase.
    assert not is_ignored_file("src/app.py", "app.py", ["SRC/*"])
    assert is_ignored_file("src/app.py", "app.py", ["src/*"])


def test_second_brainignore_is_not_indexed():
    assert is_ignored_file(".secondbrainignore", ".secondbrainignore", [])


def test_ignored_dirs():
    assert is_ignored_dir("__pycache__")
    assert is_ignored_dir("foo.egg-info")
    assert not is_ignored_dir("src")
