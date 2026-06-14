"""Tests for the one-shot assessment."""

from __future__ import annotations

from pathlib import Path

from second_brain import assess

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def test_assess_metrics():
    r = assess.assess(FIXTURE)
    assert r["project"] == "sample_project"
    assert r["files"] == 8
    assert r["truncated"] == 0
    assert r["empty"] == 0          # empty __init__.py is excluded
    assert r["tokens_digest"] > 0
    assert r["graph_bytes"] > 0


def test_render_markdown():
    md = assess.render_markdown(assess.assess(FIXTURE))
    assert "assessment of `sample_project`" in md
    assert "Token cost to orient an assistant" in md
    assert "What was hidden" in md


def test_assess_lists_problem_file_names(tmp_path):
    """The report names the truncated/empty files, not just their counts."""
    (tmp_path / "bad.txt").write_bytes(b"text\n" + b"\x00" * 64)
    (tmp_path / "empty.txt").write_bytes(b"")
    r = assess.assess(tmp_path)
    assert "bad.txt" in r["truncated_files"]
    assert "empty.txt" in r["empty_files"]
    md = assess.render_markdown(r)
    assert "`bad.txt`" in md and "`empty.txt`" in md


def test_utf16_not_truncated_but_corruption_is(tmp_path):
    from second_brain.indexer import build_graph

    # Valid UTF-16 text (BOM + alternating nulls) must NOT be flagged as truncated.
    (tmp_path / "u.txt").write_bytes("hello world\nsecond line\n".encode("utf-16"))
    # Genuine corruption: real text + a contiguous null run -> flagged.
    (tmp_path / "bad.txt").write_bytes(b"real content here\n" + b"\x00" * 500)
    g = build_graph(tmp_path)
    integ = assess.scan_integrity(tmp_path, g)
    assert "u.txt" not in integ["truncated"]
    assert "bad.txt" in integ["truncated"]


def test_mixed_utf8_utf16_log_is_not_truncated(tmp_path):
    """A log mixing a UTF-8 line and a UTF-16LE section (no BOM, no contiguous null run) is valid
    text, not truncation. Regression 0.1.2: such PowerShell trigger logs were false-positived."""
    from second_brain.indexer import build_graph

    content = b"2026-06-08 23:05:00  avvio\r\n" + "[accordatore] x\n".encode("utf-16-le")
    (tmp_path / "trigger.log").write_bytes(content)
    g = build_graph(tmp_path)
    assert "trigger.log" not in assess.scan_integrity(tmp_path, g)["truncated"]


def test_report_counts_all_files_not_just_docs(tmp_path):
    """On a code-only project the 'without SB' number must reflect all files, not ~0 docs."""
    (tmp_path / "a.py").write_text("x = 1\n" * 50)
    (tmp_path / "b.py").write_text("y = 2\n" * 50)
    r = assess.assess(tmp_path)
    assert r["tokens_read_all_files"] >= r["tokens_read_all_docs"]
    md = assess.render_markdown(r)
    assert "read every indexed file" in md


def test_utf16_with_zerofill_tail_is_flagged(tmp_path):
    """A UTF-16-shaped head followed by a contiguous null run is truncation, not encoding."""
    from second_brain.indexer import build_graph

    head = "hello world this is text".encode("utf-16")
    (tmp_path / "mix.txt").write_bytes(head + b"\x00" * 64)
    g = build_graph(tmp_path)
    assert "mix.txt" in assess.scan_integrity(tmp_path, g)["truncated"]


def test_zerofill_past_scan_cap_caught_by_tail(tmp_path, monkeypatch):
    """Zero-fill beyond the head scan cap is still caught by the tail scan."""
    from second_brain import assess as a
    from second_brain.indexer import build_graph

    monkeypatch.setattr(a, "_SCAN_CAP", 1024)
    (tmp_path / "big.txt").write_bytes(b"x" * 4096 + b"\x00" * 256)  # hole is past the cap
    g = build_graph(tmp_path)
    assert "big.txt" in a.scan_integrity(tmp_path, g)["truncated"]
