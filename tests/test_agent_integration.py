"""Tests for agent integration: context files, Claude hook, git hooks, hook-context."""

from __future__ import annotations

import json

from second_brain import agent_integration as ai


# --------------------------------------------------------------------------- context files
def test_install_collapses_duplicate_blocks(tmp_path):
    # Two stale SB blocks around user content must collapse to exactly one on (re)install,
    # and uninstall must remove all of ours while keeping the user content.
    block = ai._block()
    (tmp_path / "CLAUDE.md").write_text(
        block + "\n\nUSER TEXT\n\n" + block + "\n", encoding="utf-8"
    )
    ai.write_context_files(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count(ai._START) == 1 and text.count(ai._END) == 1
    assert "USER TEXT" in text
    ai.remove_context_files(tmp_path)
    text2 = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert ai._START not in text2 and "USER TEXT" in text2


def test_write_context_files_creates_and_is_idempotent(tmp_path):
    res = ai.write_context_files(tmp_path)
    assert res == {"CLAUDE.md": "created", "AGENTS.md": "created"}
    claude = tmp_path / "CLAUDE.md"
    text = claude.read_text(encoding="utf-8")
    assert "Second Brain" in text and "GRAPH_REPORT.md" in text
    assert text.count("<!-- second-brain:start -->") == 1
    # re-run updates in place, no duplicate block
    res2 = ai.write_context_files(tmp_path)
    assert res2["CLAUDE.md"] == "updated"
    assert claude.read_text(encoding="utf-8").count("<!-- second-brain:start -->") == 1


def test_write_context_files_appends_preserving_existing(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# My project\n\nExisting notes.\n", encoding="utf-8")
    res = ai.write_context_files(tmp_path)
    assert res["CLAUDE.md"] == "appended"
    text = claude.read_text(encoding="utf-8")
    assert "Existing notes." in text
    assert text.count("<!-- second-brain:start -->") == 1


def test_remove_context_files_keeps_other_content(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# My project\n\nExisting notes.\n", encoding="utf-8")
    ai.write_context_files(tmp_path)
    res = ai.remove_context_files(tmp_path)
    assert res["CLAUDE.md"] == "removed"
    text = claude.read_text(encoding="utf-8")
    assert "Existing notes." in text
    assert "second-brain:start" not in text


def test_remove_context_files_deletes_block_only_file(tmp_path):
    ai.write_context_files(tmp_path)  # creates files holding only our block
    ai.remove_context_files(tmp_path)
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()


# --------------------------------------------------------------------------- Claude hook
def test_install_claude_hook_creates_and_idempotent(tmp_path):
    assert ai.install_claude_hook(tmp_path) == "installed"
    p = tmp_path / ".claude" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    pre = data["hooks"]["PreToolUse"]
    assert any(h["command"] == "second-brain hook-context"
               for e in pre for h in e["hooks"])
    assert ai.install_claude_hook(tmp_path) == "present"  # no duplicate
    data2 = json.loads(p.read_text(encoding="utf-8"))
    assert len(data2["hooks"]["PreToolUse"]) == 1


def test_install_claude_hook_preserves_existing(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
        ]}
    }), encoding="utf-8")
    ai.install_claude_hook(tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    cmds = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "echo hi" in cmds and "second-brain hook-context" in cmds


def test_uninstall_claude_hook(tmp_path):
    ai.install_claude_hook(tmp_path)
    assert ai.uninstall_claude_hook(tmp_path) == "removed"
    p = tmp_path / ".claude" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    cmds = [h["command"] for e in data.get("hooks", {}).get("PreToolUse", []) for h in e["hooks"]]
    assert "second-brain hook-context" not in cmds
    assert ai.uninstall_claude_hook(tmp_path) == "absent"


def test_uninstall_claude_hook_keeps_other_hooks(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
        ]}
    }), encoding="utf-8")
    ai.install_claude_hook(tmp_path)
    ai.uninstall_claude_hook(tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    cmds = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert cmds == ["echo hi"]


# --------------------------------------------------------------------------- git hooks
def test_install_git_hook_requires_git(tmp_path):
    assert "error" in ai.install_git_hook(tmp_path)


def test_install_git_hook_creates_and_idempotent(tmp_path):
    (tmp_path / ".git").mkdir()
    res = ai.install_git_hook(tmp_path)
    assert res == {"post-commit": "created", "post-checkout": "created"}
    pc = tmp_path / ".git" / "hooks" / "post-commit"
    assert pc.is_file() and "second-brain build" in pc.read_text(encoding="utf-8")
    res2 = ai.install_git_hook(tmp_path)
    assert res2["post-commit"] == "updated"  # idempotent re-write of our block (no duplication)
    assert pc.read_text(encoding="utf-8").count("second-brain build") == 1


def test_install_git_hook_appends_to_existing(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "post-commit").write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    res = ai.install_git_hook(tmp_path)
    assert res["post-commit"] == "appended"
    text = (hooks / "post-commit").read_text(encoding="utf-8")
    assert "echo existing" in text and "second-brain build" in text


def test_uninstall_git_hook(tmp_path):
    (tmp_path / ".git").mkdir()
    ai.install_git_hook(tmp_path)
    res = ai.uninstall_git_hook(tmp_path)
    assert res["post-commit"] == "removed"
    # file created solely by us is deleted
    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()


def test_uninstall_git_hook_keeps_existing(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "post-commit").write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    ai.install_git_hook(tmp_path)
    ai.uninstall_git_hook(tmp_path)
    text = (hooks / "post-commit").read_text(encoding="utf-8")
    assert "echo existing" in text and "second-brain build" not in text


# --------------------------------------------------------------------------- hook-context
def test_hook_context_empty_without_graph(tmp_path):
    assert ai.hook_context(tmp_path) == ""


def test_hook_context_json_with_graph(tmp_path):
    store = tmp_path / ".secondbrain"
    store.mkdir()
    (store / "graph.json").write_text("{}", encoding="utf-8")
    out = ai.hook_context(tmp_path)
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "GRAPH_REPORT.md" in payload["hookSpecificOutput"]["additionalContext"]
