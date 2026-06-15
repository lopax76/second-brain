"""Tests for impact --diff: blast radius of the working-tree changes."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from second_brain import operational, query
from second_brain.cli import main
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

_HAS_GIT = shutil.which("git") is not None


def _g() -> Graph:
    g = Graph(project="t")
    for x in ("a.py", "b.py", "c.py"):
        g.add_node(Node(id=x, type=NodeType.PROGRAM, label=x, path=x))
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))  # a depends on b
    g.add_edge(Edge("c.py", "b.py", EdgeType.IMPORTS))  # c depends on b
    return g


def test_impact_diff_union_and_unindexed():
    res = query.impact_diff(_g(), ["b.py", "new.py"], direction="up")
    assert res["seeds"] == ["b.py"]
    assert "new.py" in res["unindexed"]
    affected = {r["id"] for depth in res["upstream"].values() for r in depth}
    assert affected == {"a.py", "c.py"}  # both depend on the changed b.py


def test_working_changes_non_git(tmp_path):
    assert operational.working_changes(tmp_path) == []


@pytest.mark.skipif(not _HAS_GIT, reason="git not available")
def test_working_changes_lists_untracked(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert "a.py" in operational.working_changes(tmp_path)


@pytest.mark.skipif(not _HAS_GIT, reason="git not available")
def test_working_changes_excludes_store_dir(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".secondbrain").mkdir()
    (tmp_path / ".secondbrain" / "graph.json").write_text("{}", encoding="utf-8")
    changes = operational.working_changes(tmp_path)
    assert "a.py" in changes
    assert not any(p.startswith(".secondbrain/") for p in changes)  # tool output, not a change


@pytest.mark.skipif(not _HAS_GIT, reason="git not available")
def test_cli_impact_diff(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "util.py").write_text("def u():\n    return 1\n", encoding="utf-8")
    (proj / "app.py").write_text("import util\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=proj, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=proj, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=proj, capture_output=True)
    assert main(["build", str(proj)]) == 0
    (proj / "util.py").write_text("def u():\n    return 2\n", encoding="utf-8")  # working change
    assert main(["impact", "--diff", str(proj)]) == 0


def test_impact_still_works_without_node_optional(tmp_path):
    # the node positional became optional for --diff; the normal form must still work
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "util.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "app.py").write_text("import util\n", encoding="utf-8")
    assert main(["build", str(proj)]) == 0
    assert main(["impact", "util.py", str(proj)]) == 0       # normal form still works
    assert main(["impact", "does/not/exist", str(proj)]) == 1  # unknown node
    assert main(["impact"]) == 2  # no node and no --diff -> usage error (returns before building)
