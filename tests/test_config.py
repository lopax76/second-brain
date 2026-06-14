"""Tests for per-project classification config (.secondbrain.json) — v0.2."""

from __future__ import annotations

import json

from second_brain import config
from second_brain.classify import classify, default_rules, rules_from_config
from second_brain.freshness import index
from second_brain.model import NodeType


def _write_cfg(root, obj) -> None:
    (root / ".secondbrain.json").write_text(json.dumps(obj), encoding="utf-8")


def test_missing_config_is_defaults(tmp_path):
    assert config.load_config(tmp_path) == config.ClassifyConfig()
    assert rules_from_config(config.load_config(tmp_path)) is rules_from_config(None)


def test_malformed_config_is_failsafe(tmp_path):
    (tmp_path / ".secondbrain.json").write_text("{ not json", encoding="utf-8")
    assert config.load_config(tmp_path) == config.ClassifyConfig()


def test_defaults_are_depersonalized():
    # Project-specific names are no longer baked into the tool's built-in taxonomy...
    assert "progetto.md" not in default_rules().structure_names
    # ...but a loose document still falls back to STRUCTURE.
    assert classify("progetto.md") is NodeType.STRUCTURE


def test_extend_adds_design_keyword(tmp_path):
    _write_cfg(tmp_path, {"classify": {"keywords": {"design": ["wireframe"]}}})
    rules = rules_from_config(config.load_config(tmp_path))
    assert classify("ui/login-wireframe.md", rules) is NodeType.DESIGN
    assert classify("docs/design-x.md", rules) is NodeType.DESIGN  # defaults still active


def test_extend_structure_name(tmp_path):
    _write_cfg(tmp_path, {"classify": {"structure_names": ["progetto.md"]}})
    rules = rules_from_config(config.load_config(tmp_path))
    assert "progetto.md" in rules.structure_names
    assert classify("README.md", rules) is NodeType.STRUCTURE  # default kept


def test_replace_mode_drops_defaults(tmp_path):
    _write_cfg(tmp_path, {"classify": {"mode": "replace", "keywords": {"design": ["wireframe"]}}})
    rules = rules_from_config(config.load_config(tmp_path))
    assert classify("ui/wireframe.md", rules) is NodeType.DESIGN
    # a default design keyword no longer matches under replace -> STRUCTURE fallback
    assert classify("docs/blueprint.md", rules) is NodeType.STRUCTURE


def test_decision_prefix_extension(tmp_path):
    _write_cfg(tmp_path, {"classify": {"decision_id_prefixes": ["DEC"]}})
    (tmp_path / "README.md").write_text("We adopted DEC-7 and ADR-0001.\n", encoding="utf-8")
    g, _ = index(tmp_path)
    assert "decision:DEC-7" in g.nodes
    assert "decision:ADR-0001" in g.nodes  # built-ins still recognised


def test_decision_default_ignores_unknown_prefix(tmp_path):
    (tmp_path / "README.md").write_text("We adopted DEC-7 and ADR-0001.\n", encoding="utf-8")
    g, _ = index(tmp_path)
    assert "decision:DEC-7" not in g.nodes  # DEC- is not a default prefix
    assert "decision:ADR-0001" in g.nodes


def test_config_file_not_indexed(tmp_path):
    _write_cfg(tmp_path, {"classify": {}})
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    g, _ = index(tmp_path)
    assert ".secondbrain.json" not in g.nodes
