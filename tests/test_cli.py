"""End-to-end CLI tests on a temporary copy of the fixture (writes stay in tmp)."""

from __future__ import annotations

import shutil
from pathlib import Path

from second_brain.cli import main

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


def test_second_build_reports_reuse_and_full_forces_a_re_read(tmp_path, capsys):
    """The incremental path and ``--full`` must be observable, not just implemented."""
    proj = _project(tmp_path)

    assert main(["build", str(proj)]) == 0
    assert "reused:" not in capsys.readouterr().out  # nothing to reuse on a first build

    assert main(["build", str(proj)]) == 0
    assert "reused:" in capsys.readouterr().out

    assert main(["build", str(proj), "--full"]) == 0
    assert "reused:" not in capsys.readouterr().out  # --full really ignores the cache


def test_build_that_cannot_persist_says_so_and_exits_nonzero(tmp_path, capsys, monkeypatch):
    """A hook or CI must be able to tell that nothing was written without parsing prose."""
    from second_brain import store

    proj = _project(tmp_path)

    def refuse(*_a, **_k):
        raise OSError("read-only store")

    monkeypatch.setattr(store, "save", refuse)
    assert main(["build", str(proj)]) == 1
    captured = capsys.readouterr()
    assert "warning: could not write the store" in captured.err
    assert "built '" in captured.out  # the graph is still reported


def test_build_survives_a_report_that_cannot_be_written(tmp_path, capsys, monkeypatch):
    from second_brain import report, store

    proj = _project(tmp_path)

    def refuse(*_a, **_k):
        raise OSError("read-only store")

    monkeypatch.setattr(store, "save", refuse)
    monkeypatch.setattr(report, "write_report", refuse)
    assert main(["build", str(proj)]) == 1  # no traceback escapes
    assert "built '" in capsys.readouterr().out


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
    assert "vis.Network" in html              # the rendering library is inlined


def test_stats_runs(tmp_path):
    proj = _project(tmp_path)
    assert main(["stats", str(proj)]) == 0


def test_query_commands_run(tmp_path):
    proj = _project(tmp_path)
    assert main(["build", str(proj)]) == 0
    assert main(["map", str(proj)]) == 0
    assert main(["find", "util", str(proj)]) == 0
    assert main(["neighbors", "src/app.py", str(proj)]) == 0
    assert main(["impact", "src/app.py", str(proj)]) == 0
    assert main(["impact", "src/app.py", str(proj), "--up"]) == 0
    assert main(["impact", "src/app.py", str(proj), "--down", "--depth", "1"]) == 0
    assert main(["assess", str(proj)]) == 0
    assert main(["view", "--backbone", str(proj)]) == 0


def test_impact_unknown_node_returns_1(tmp_path):
    proj = _project(tmp_path)
    main(["build", str(proj)])
    assert main(["impact", "does/not/exist", str(proj)]) == 1


def test_find_prints_true_total_when_capped(tmp_path, capsys):
    """A capped display must still report the real total (no lying counter)."""
    proj = tmp_path / "many"
    proj.mkdir()
    for i in range(60):
        (proj / f"util_{i:02d}.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["build", str(proj)]) == 0
    assert main(["find", "util", str(proj), "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "60 matches" in out and "showing 5" in out
    capsys.readouterr()
    assert main(["find", "util", str(proj), "--all"]) == 0
    assert capsys.readouterr().out.count("util_") >= 60


def test_report_cli_writes_file(tmp_path):
    proj = _project(tmp_path)
    assert main(["build", str(proj)]) == 0
    assert main(["report", str(proj)]) == 0
    assert (proj / ".secondbrain" / "GRAPH_REPORT.md").is_file()


def test_agent_install_uninstall_cli(tmp_path):
    proj = _project(tmp_path)
    assert main(["agent", "install", str(proj)]) == 0
    assert (proj / "CLAUDE.md").is_file() and (proj / "AGENTS.md").is_file()
    assert main(["agent", "uninstall", str(proj)]) == 0
    assert not (proj / "CLAUDE.md").exists()


def test_hook_cli_requires_git_then_installs(tmp_path):
    proj = _project(tmp_path)
    assert main(["hook", "install", str(proj)]) == 1  # no .git yet
    (proj / ".git").mkdir()
    assert main(["hook", "install", str(proj)]) == 0
    assert (proj / ".git" / "hooks" / "post-commit").is_file()
    assert main(["hook-context", str(proj)]) == 0


def test_cli_query_auto_refreshes(tmp_path, capsys):
    proj = _project(tmp_path)
    assert main(["build", str(proj)]) == 0
    (proj / "newmod.py").write_text("z = 1\n", encoding="utf-8")  # change after build
    capsys.readouterr()
    assert main(["find", "newmod", str(proj)]) == 0
    assert "newmod.py" in capsys.readouterr().out  # query saw it without a manual rebuild


def test_build_symbols_cli_e2e(tmp_path):
    import json
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert main(["build", "--symbols", str(proj)]) == 0
    g = json.loads((proj / ".secondbrain" / "graph.json").read_text(encoding="utf-8"))
    assert any(n["type"] == "symbol" for n in g["nodes"])
    assert (proj / ".secondbrain" / "mode.json").is_file()


def test_focus_cli_runs(tmp_path):
    proj = _project(tmp_path)
    assert main(["build", str(proj)]) == 0
    assert main(["focus", "util", str(proj)]) == 0
    assert main(["focus", "util", str(proj), "--budget", "500"]) == 0


def test_symbols_cli_accepts_optional_path(tmp_path):
    """symbols takes an optional project root like the other commands (file resolved under it)."""
    proj = _project(tmp_path)
    # second positional must NOT be 'unrecognized arguments' (the B1 regression)
    assert main(["symbols", "src/app.py", str(proj)]) == 0


def test_symbols_cli_missing_file_returns_2_loudly(tmp_path, capsys):
    """A missing file fails loudly (exit 2 + stderr), never silently."""
    assert main(["symbols", "nope.py", str(tmp_path)]) == 2
    assert "not a file" in capsys.readouterr().err


def test_gate_passes_on_clean_project(tmp_path):
    proj = tmp_path / "clean"
    proj.mkdir()
    (proj / "README.md").write_text("# clean project\nno links here\n", encoding="utf-8")
    (proj / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["build", str(proj)]) == 0
    assert main(["gate", str(proj)]) == 0
