"""End-to-end CLI tests on a temporary copy of the fixture (writes stay in tmp)."""

from __future__ import annotations

import shutil
from pathlib import Path

from secondbrain.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _project(tmp_path) -> Path:
    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    return proj


def test_build_writes_store(tmp_path):
    proj = _project(tmp_path)
    assert main(["build", str(proj)]) == 0
    assert (proj / ".secondbrain" / "graph.json").is_file()
    assert (proj / ".secondbrain" / "manifest.json").is_file()


def test_gate_fails_on_broken_ref(tmp_path):
    proj = _project(tmp_path)
    main(["build", str(proj)])
    # fixture contains one broken reference (missing.md) -> gate exit 1
    assert main(["gate", str(proj)]) == 1


def test_gate_without_build_returns_2(tmp_path):
    assert main(["gate", str(tmp_path)]) == 2


def test_view_is_self_contained(tmp_path):
    proj = _project(tmp_path)
    assert main(["view", str(proj)]) == 0
    html = (proj / ".secondbrain" / "view.html").read_text(encoding="utf-8")
    assert "__SB_DATA__" not in html          # token was replaced
    assert '"project": "proj"' in html or '"project":"proj"' in html
    assert "ForceGraph3D" in html             # the 3D library is referenced


def test_stats_runs(tmp_path):
    proj = _project(tmp_path)
    assert main(["stats", str(proj)]) == 0
