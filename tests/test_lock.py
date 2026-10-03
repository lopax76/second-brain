"""The store write lock: one writer per store, across real processes."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from second_brain import freshness, lock, store

_HOLDER = """
import sys, time
from second_brain import lock
with lock.write_lock(sys.argv[1]):
    print("preso", flush=True)
    time.sleep(float(sys.argv[2]))
"""


def _hold(store_dir, seconds: float) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", _HOLDER, str(store_dir), str(seconds)],
                         stdout=subprocess.PIPE, text=True,
                         env={**__import__("os").environ, "SECOND_BRAIN_AGENT": "codex"})
    assert p.stdout is not None and p.stdout.readline().strip() == "preso"
    return p


def test_a_second_process_is_told_who_holds_the_store(tmp_path):
    p = _hold(tmp_path, 3)
    try:
        with pytest.raises(lock.Busy) as info, lock.write_lock(tmp_path):
            pass
        assert info.value.holder.get("agent") == "codex"
    finally:
        p.wait()
    with lock.write_lock(tmp_path):  # released when the holder exits
        pass


def test_different_stores_never_wait_on_each_other(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    p = _hold(a, 3)
    try:
        t0 = time.monotonic()
        with lock.write_lock(b):
            pass
        assert time.monotonic() - t0 < 1
    finally:
        p.wait()


def test_a_busy_store_serves_the_old_graph_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    freshness.load_or_refresh(tmp_path)  # first build
    (tmp_path / "b.md").write_text("# b, nuovo\n", encoding="utf-8")
    p = _hold(store.store_dir(tmp_path), 4)
    try:
        g = freshness.load_or_refresh(tmp_path, refresh=True)
        assert "b.md" not in g.nodes
        assert freshness.last_problem and freshness.last_problem["kind"] == "busy"
    finally:
        p.wait()
    g = freshness.load_or_refresh(tmp_path, refresh=True)
    assert "b.md" in g.nodes and freshness.last_problem is None


def test_a_failed_refresh_is_no_longer_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    freshness.load_or_refresh(tmp_path)
    (tmp_path / "b.md").write_text("# b\n", encoding="utf-8")

    def boom(*a, **k):
        raise MemoryError("finta")
    monkeypatch.setattr(freshness, "index_cached", boom)
    g = freshness.load_or_refresh(tmp_path, refresh=True)
    assert "a.md" in g.nodes
    assert freshness.last_problem and freshness.last_problem["kind"] == "refresh-failed"
    assert "MemoryError" in freshness.last_problem["message"]


def test_after_the_lock_a_rebuild_already_done_by_the_previous_holder_is_reused(
        tmp_path, monkeypatch):
    """The decision to rebuild is taken before the lock; once holding it, re-check: if the
    previous holder already refreshed the store, serve ITS graph and do not rebuild over it."""
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    monkeypatch.setenv("SECOND_BRAIN_AGENT", "claude-code")
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    freshness.load_or_refresh(tmp_path)
    (tmp_path / "b.md").write_text("# b\n", encoding="utf-8")
    # another agent refreshes the store in its own process...
    subprocess.run([sys.executable, "-c",
                    "import sys\nfrom second_brain import freshness\n"
                    "freshness.load_or_refresh(sys.argv[1], refresh=True)", str(tmp_path)],
                   check=True, env={**__import__("os").environ, "SECOND_BRAIN_AGENT": "codex"})
    # ...while we had already decided the store was stale: simulate that stale decision
    real = freshness.is_stale
    calls = {"n": 0}

    def stale_once(root):
        calls["n"] += 1
        return True if calls["n"] == 1 else real(root)
    monkeypatch.setattr(freshness, "is_stale", stale_once)
    rebuilt = {"n": 0}
    real_index = freshness.index_cached

    def counting(*a, **k):
        rebuilt["n"] += 1
        return real_index(*a, **k)
    monkeypatch.setattr(freshness, "index_cached", counting)

    g = freshness.load_or_refresh(tmp_path, refresh=True)
    assert "b.md" in g.nodes                      # the other agent's work is what we serve
    assert rebuilt["n"] == 0                      # and we did not rebuild over it
    assert freshness.last_handover and freshness.last_handover["agent"] == "codex"
