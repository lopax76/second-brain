"""Direct classification heuristic tests (decision / design / report / memory)."""

from __future__ import annotations

from secondbrain.classify import classify
from secondbrain.model import NodeType


def test_decision_design_report_memory() -> None:
    assert classify("adr-0001.md") is NodeType.DECISION
    assert classify("docs/design-blueprint.md") is NodeType.DESIGN
    assert classify("notes/report-2026-01-01.md") is NodeType.REPORT
    assert classify("memory/notes.md") is NodeType.MEMORY


def test_program_data_config_structure() -> None:
    assert classify("src/app.py") is NodeType.PROGRAM
    assert classify("data/store.csv") is NodeType.DATA
    assert classify("config.toml") is NodeType.CONFIG
    assert classify("README.md") is NodeType.STRUCTURE
