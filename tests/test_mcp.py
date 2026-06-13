"""Smoke test for the optional MCP server (skipped if the 'mcp' extra is absent)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from second_brain.mcp_server import build_server  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def test_build_server_constructs():
    server = build_server(str(FIXTURE))
    assert server is not None
    assert server.name == "second-brain"
