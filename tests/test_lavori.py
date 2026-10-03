"""0.10: the work registry keeps two agents from overwriting each other."""

from __future__ import annotations

import json
import os
import time

from second_brain import freshness, lavori, workspace


def _ws(tmp_path):
    root = tmp_path / "Documents"
    for name in ("Alfa", "Beta"):
        (root / name).mkdir(parents=True)
        (root / name / "PROGETTO.md").write_text(f"# {name}\n", encoding="utf-8")
    (root / "Alfa" / "a.py").write_text("import b\n", encoding="utf-8")
    (root / "Alfa" / "b.py").write_text("X = 1\n", encoding="utf-8")
    (root / "Alfa" / "c.md").write_text("# c\n", encoding="utf-8")
    (root / workspace.WORKSPACE_FILE).write_text(json.dumps({"memorie": []}), encoding="utf-8")
    return root


def test_different_projects_never_block_each_other(tmp_path):
    root = _ws(tmp_path)
    assert lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")["esito"] == "ok"
    assert lavori.posso_scrivere(root / "Beta" / "PROGETTO.md", "codex")["esito"] == "ok"


def test_the_same_file_is_blocked_for_the_other_agent(tmp_path):
    root = _ws(tmp_path)
    assert lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")["esito"] == "ok"
    res = lavori.posso_scrivere(root / "Alfa" / "a.py", "codex")
    assert res["esito"] == "blocco" and "claude-code" in res["motivo"]
    # the agent that holds it is never blocked by itself
    assert lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")["esito"] == "ok"


def test_declared_files_are_protected_before_being_touched(tmp_path):
    root = _ws(tmp_path)
    lavori.inizia(root / "Alfa", "codex", intento="refactor di c", file=["c.md"])
    res = lavori.posso_scrivere(root / "Alfa" / "c.md", "claude-code")
    assert res["esito"] == "blocco" and "refactor di c" in res["motivo"]


def test_a_linked_file_gets_a_warning_not_a_block(tmp_path):
    root = _ws(tmp_path)
    freshness.load_or_refresh(root / "Alfa")          # a.py imports b.py
    assert lavori.posso_scrivere(root / "Alfa" / "b.py", "codex")["esito"] == "ok"
    res = lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")
    assert res["esito"] == "attenzione" and "codex" in res["motivo"]


def test_closing_a_work_frees_its_files(tmp_path):
    root = _ws(tmp_path)
    lavori.posso_scrivere(root / "Alfa" / "a.py", "codex")
    assert lavori.chiudi(root / "Alfa", "codex")["toccati"] == ["a.py"]
    assert lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")["esito"] == "ok"


def test_an_abandoned_work_expires(tmp_path, monkeypatch):
    root = _ws(tmp_path)
    lavori.posso_scrivere(root / "Alfa" / "a.py", "codex")
    later = time.time() + (lavori.SCADENZA_MIN + 1) * 60
    monkeypatch.setattr(lavori, "_now", lambda: later)
    assert lavori.posso_scrivere(root / "Alfa" / "a.py", "claude-code")["esito"] == "ok"


def test_a_file_changed_by_someone_else_since_my_write_is_flagged(tmp_path):
    root = _ws(tmp_path)
    f = root / "Alfa" / "c.md"
    assert lavori.posso_scrivere(f, "claude-code")["esito"] == "ok"
    f.write_text("# c, scritto da claude\n", encoding="utf-8")
    lavori.dopo_scrittura(f, "claude-code")
    f.write_text("# c, riscritto da un editor esterno, piu' lungo\n", encoding="utf-8")
    os.utime(f, None)
    res = lavori.posso_scrivere(f, "claude-code")
    assert res["esito"] == "attenzione" and "rileggilo" in res["motivo"]


def test_my_own_write_is_never_flagged(tmp_path):
    root = _ws(tmp_path)
    f = root / "Alfa" / "c.md"
    lavori.posso_scrivere(f, "claude-code")
    f.write_text("# c bis\n", encoding="utf-8")
    lavori.dopo_scrittura(f, "claude-code")
    assert lavori.posso_scrivere(f, "claude-code")["esito"] == "ok"


def test_in_corso_lists_active_works_per_project(tmp_path):
    root = _ws(tmp_path)
    lavori.inizia(root / "Alfa", "codex", intento="test")
    lavori.inizia(root / "Beta", "claude-code", intento="docs")
    rows = {(r["progetto"], r["agente"]) for r in lavori.in_corso(root)}
    assert rows == {("alfa", "codex"), ("beta", "claude-code")}


def test_the_claude_code_hook_denies_a_contested_write(tmp_path):
    """End to end through the CLI, with the JSON Claude Code sends on stdin."""
    import subprocess
    import sys

    root = _ws(tmp_path)
    lavori.posso_scrivere(root / "Alfa" / "a.py", "codex")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "s1",
               "cwd": str(root / "Alfa"), "tool_input": {"file_path": "a.py"}}
    out = subprocess.run([sys.executable, "-m", "second_brain", "hook-scrittura"],
                         input=json.dumps(payload), capture_output=True, text=True, check=True)
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "codex" in decision["permissionDecisionReason"]

    payload["tool_input"] = {"file_path": str(root / "Alfa" / "c.md")}
    out = subprocess.run([sys.executable, "-m", "second_brain", "hook-scrittura"],
                         input=json.dumps(payload), capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""  # free file: allowed silently
