"""The gate's 'no baseline' contract: a None old-manifest reports no stale files."""

from __future__ import annotations

from second_brain import gate
from second_brain.freshness import build_manifest, index


def test_no_baseline_reports_no_stale(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# a\n", encoding="utf-8")
    g, _ = index(tmp_path)
    rep = gate.evaluate(g, None, build_manifest(tmp_path))
    assert rep.stale_count == 0
    assert rep.ok  # no broken references either
