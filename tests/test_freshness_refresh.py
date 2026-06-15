"""Self-refreshing reads: queries never answer from a stale map."""

from __future__ import annotations

from second_brain import store
from second_brain.freshness import (
    auto_refresh_enabled,
    fast_signature,
    index,
    is_stale,
    load_or_refresh,
)
from second_brain.model import NodeType


def test_first_touch_builds_and_writes_signature(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    g = load_or_refresh(tmp_path)
    assert "a.py" in g.nodes
    assert (tmp_path / ".secondbrain" / "signature.json").is_file()
    assert is_stale(tmp_path) is False


def test_query_sees_new_file_without_manual_rebuild(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    g1 = load_or_refresh(tmp_path)
    assert "b.py" not in g1.nodes
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")  # new file -> set changes
    g2 = load_or_refresh(tmp_path)
    assert "b.py" in g2.nodes  # auto-refreshed, no manual build


def test_refresh_false_serves_stale_on_purpose(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    load_or_refresh(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    g = load_or_refresh(tmp_path, refresh=False)
    assert "b.py" not in g.nodes


def test_is_stale_detects_change(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    load_or_refresh(tmp_path)
    assert is_stale(tmp_path) is False
    (tmp_path / "c.py").write_text("z = 3\n", encoding="utf-8")
    assert is_stale(tmp_path) is True


def test_no_signature_is_stale(tmp_path):
    # An old store with graph.json but no signature.json must be treated as stale (rebuild once).
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    g, m = index(tmp_path)
    store.save(tmp_path, g, m)  # no signature
    assert is_stale(tmp_path) is True


def test_env_toggle(monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_AUTO_REFRESH", "0")
    assert auto_refresh_enabled() is False
    monkeypatch.setenv("SECOND_BRAIN_AUTO_REFRESH", "off")
    assert auto_refresh_enabled() is False
    monkeypatch.setenv("SECOND_BRAIN_AUTO_REFRESH", "1")
    assert auto_refresh_enabled() is True
    monkeypatch.delenv("SECOND_BRAIN_AUTO_REFRESH", raising=False)
    assert auto_refresh_enabled() is True  # default on


def test_readonly_store_degrades_not_crashes(tmp_path, monkeypatch):
    # If the store can't be written (read-only checkout), a query must still answer with the
    # rebuilt graph instead of crashing.
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    load_or_refresh(tmp_path)  # first build saves fine
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")  # -> stale

    import second_brain.store as store_mod

    def _boom(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(store_mod, "save", _boom)
    g = load_or_refresh(tmp_path)  # rebuild ok, save fails -> must NOT raise
    assert "b.py" in g.nodes  # the freshly rebuilt graph is returned anyway


def test_refresh_ttl_throttles_check(tmp_path, monkeypatch):
    import second_brain.freshness as fr

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    load_or_refresh(tmp_path)
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "60")
    fr._LAST_CHECK.clear()
    calls = {"n": 0}
    real = fr.is_stale
    monkeypatch.setattr(fr, "is_stale", lambda r: (calls.__setitem__("n", calls["n"] + 1)
                                                   or real(r)))
    load_or_refresh(tmp_path)                                   # 1st: checks
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")  # change
    g = load_or_refresh(tmp_path)                              # within TTL: check skipped
    assert calls["n"] == 1                                      # only the first call checked
    assert "b.py" not in g.nodes                               # throttled -> not refreshed yet


def test_symbols_mode_persisted_even_with_zero_symbols(tmp_path):
    # A --symbols build of a docs-only tree stores 0 symbol nodes; when code is later added,
    # the auto-refresh must STILL index symbols (mode is persisted, not inferred from nodes).
    (tmp_path / "readme.md").write_text("# docs only\n", encoding="utf-8")
    g, m = index(tmp_path, symbols=True)
    store.save(tmp_path, g, m, signature=fast_signature(tmp_path), symbols=True)
    assert not any(n.type is NodeType.SYMBOL for n in g.nodes.values())  # nothing to extract yet
    assert (tmp_path / ".secondbrain" / "mode.json").is_file()
    (tmp_path / "core.py").write_text(
        "def f():\n    return 1\n\n\nclass A:\n    def m(self):\n        pass\n", encoding="utf-8"
    )
    g2 = load_or_refresh(tmp_path)
    assert any(n.type is NodeType.SYMBOL for n in g2.nodes.values())  # symbols mode preserved


def test_rebuild_failure_degrades_not_crashes(tmp_path, monkeypatch):
    # If the rebuild itself raises (not just I/O), the query must still answer with the loaded
    # graph instead of crashing.
    import second_brain.freshness as fr

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    load_or_refresh(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")  # -> stale

    def _boom(*a, **k):
        raise ValueError("parser exploded")

    monkeypatch.setattr(fr, "index", _boom)
    g = load_or_refresh(tmp_path)  # must NOT raise
    assert "a.py" in g.nodes  # served the already-loaded (stale) graph


def test_refresh_preserves_symbols_mode(tmp_path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    g, m = index(tmp_path, symbols=True)
    store.save(tmp_path, g, m, signature=fast_signature(tmp_path))
    assert any(n.type is NodeType.SYMBOL for n in load_or_refresh(tmp_path).nodes.values())
    # change size -> stale -> refresh must rebuild in the SAME (symbols) mode
    (tmp_path / "m.py").write_text(
        "def f():\n    return 22\n\n\ndef g2():\n    pass\n", encoding="utf-8"
    )
    g2 = load_or_refresh(tmp_path)
    assert any(n.type is NodeType.SYMBOL for n in g2.nodes.values())
