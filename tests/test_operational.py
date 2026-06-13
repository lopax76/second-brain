"""Tests for operational nodes (decisions from docs, sessions from git)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from secondbrain import operational
from secondbrain.freshness import index
from secondbrain.indexer import build_graph
from secondbrain.model import EdgeType, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def test_add_decisions_from_docs():
    g = build_graph(FIXTURE)
    operational.add_decisions(g, FIXTURE)
    n = g.nodes.get("decision:D-SAMPLE-1")
    assert n is not None and n.type is NodeType.DECISION
    mentions = {(e.source, e.target) for e in g.edges if e.type is EdgeType.MENTIONS}
    assert ("README.md", "decision:D-SAMPLE-1") in mentions


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def test_add_sessions_from_git(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "t@example.com"], tmp_path)
    _git(["config", "user.name", "Tester"], tmp_path)
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "initial"], tmp_path)

    g = build_graph(tmp_path)
    operational.add_sessions(g, tmp_path)
    sessions = [n for n in g.nodes.values() if n.type is NodeType.SESSION]
    assert len(sessions) == 1
    touched = {e.target for e in g.edges if e.type is EdgeType.TOUCHES}
    assert "a.py" in touched


def test_index_enriches_with_decisions():
    g, _ = index(FIXTURE)  # operational=True by default
    assert "decision:D-SAMPLE-1" in g.nodes


def test_index_can_skip_operational():
    g, _ = index(FIXTURE, operational=False)
    assert not any(n.type is NodeType.SESSION for n in g.nodes.values())
    assert "decision:D-SAMPLE-1" not in g.nodes
