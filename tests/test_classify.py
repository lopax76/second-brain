"""Direct classification heuristic tests (decision / design / report / memory)."""

from __future__ import annotations

from second_brain.classify import classify
from second_brain.model import NodeType


def test_decision_design_report_memory() -> None:
    # A decision *file* (an ADR or a "decisioni" doc) classifies as a DESIGN document, NOT a
    # DECISION node: NodeType.DECISION is reserved for the D-XXX/ADR-N/RFC-N identifiers created
    # from document text (see test_operational). Fix 0.1.2 — avoids double-counting decisions.
    assert classify("adr-0001.md") is NodeType.DESIGN
    assert classify("docs/cryptobot-decisioni.md") is NodeType.DESIGN
    assert classify("docs/design-blueprint.md") is NodeType.DESIGN
    assert classify("notes/report-2026-01-01.md") is NodeType.REPORT
    assert classify("memory/notes.md") is NodeType.MEMORY


def test_program_data_config_structure() -> None:
    assert classify("src/app.py") is NodeType.PROGRAM
    assert classify("data/store.csv") is NodeType.DATA
    assert classify("config.toml") is NodeType.CONFIG
    assert classify("README.md") is NodeType.STRUCTURE
