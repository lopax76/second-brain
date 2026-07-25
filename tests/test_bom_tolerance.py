"""A BOM in one of SB's own config files must not silently disable it.

Notepad and PowerShell 5.1's ``Set-Content -Encoding utf8`` both prepend a UTF-8 BOM. Before
this fix the byte order mark made ``json.loads`` raise (config fell back to defaults, so
``respect_gitignore`` stayed off) and glued itself to the first ignore rule (so that rule
stopped matching). Both failures were silent — the symptom was "my .gitignore is ignored".
"""

from __future__ import annotations

from second_brain.config import load_config
from second_brain.ignore import gitignored, load_gitignore_rules, load_ignore_patterns

BOM = "﻿"


def test_config_with_bom_is_honoured(tmp_path):
    (tmp_path / ".secondbrain.json").write_text(
        BOM + '{"respect_gitignore": true}', encoding="utf-8"
    )
    assert load_config(tmp_path).respect_gitignore is True


def test_config_with_bom_keeps_classification_overrides(tmp_path):
    (tmp_path / ".secondbrain.json").write_text(
        BOM + '{"classify": {"structure_names": ["progetto.md"]}}', encoding="utf-8"
    )
    assert load_config(tmp_path).structure_names == ("progetto.md",)


def test_gitignore_first_rule_with_bom_still_matches(tmp_path):
    # A dir-only rule ("vendor/") is matched against the DIRECTORY — iter_files prunes it there,
    # so files underneath are never tested individually. Assert what the rule actually promises.
    (tmp_path / ".gitignore").write_text(BOM + "vendor/\n*.log\n", encoding="utf-8")
    rules = load_gitignore_rules(tmp_path)
    assert gitignored("vendor", True, rules)  # the FIRST rule is the one a BOM would break
    assert gitignored("ops/server.log", False, rules)  # a later rule was never at risk


def test_secondbrainignore_first_pattern_with_bom_still_matches(tmp_path):
    (tmp_path / ".secondbrainignore").write_text(BOM + "tests/fixtures/*\n", encoding="utf-8")
    assert load_ignore_patterns(tmp_path) == ["tests/fixtures/*"]


def test_no_bom_behaviour_is_unchanged(tmp_path):
    (tmp_path / ".secondbrain.json").write_text('{"respect_gitignore": true}', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    assert load_config(tmp_path).respect_gitignore is True
    assert gitignored("vendor", True, load_gitignore_rules(tmp_path))
