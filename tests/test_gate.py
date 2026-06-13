"""Tests for freshness (hash/diff), the anti-drift gate, and the store roundtrip."""

from __future__ import annotations

from pathlib import Path

from second_brain import gate, store
from second_brain.freshness import build_manifest, diff_manifest, file_hash
from second_brain.indexer import build_graph

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def test_file_hash_stable_and_changes_on_edit(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hello", encoding="utf-8")
    h1 = file_hash(p)
    p.write_text("hello", encoding="utf-8")  # same content -> same hash
    assert file_hash(p) == h1
    p.write_text("hello world", encoding="utf-8")  # changed -> different hash
    assert file_hash(p) != h1


def test_build_manifest_and_diff(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("hi\n", encoding="utf-8")
    m1 = build_manifest(tmp_path)
    assert set(m1) == {"a.py", "b.md"}

    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")  # changed
    (tmp_path / "c.txt").write_text("new\n", encoding="utf-8")   # added
    (tmp_path / "b.md").unlink()                                  # removed
    m2 = build_manifest(tmp_path)
    d = diff_manifest(m1, m2)
    assert d["changed"] == ["a.py"]
    assert d["added"] == ["c.txt"]
    assert d["removed"] == ["b.md"]


def test_find_broken_and_orphans():
    g = build_graph(FIXTURE)
    broken = gate.find_broken(g)
    assert ("README.md", "notes/missing.md") in broken

    orphans = set(gate.find_orphans(g))
    assert {"config.toml", "data/store.csv", "src/__init__.py"} <= orphans
    assert "README.md" not in orphans  # README has outgoing references


def test_evaluate_ok_then_stale(tmp_path):
    # Copy fixture into a writable temp project.
    import shutil

    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    g = build_graph(proj)
    m = build_manifest(proj)

    rep = gate.evaluate(g, m, m)
    assert rep.stale_count == 0
    assert rep.broken  # the fixture has one broken ref -> not ok
    assert rep.ok is False

    # Edit a file -> stale appears.
    (proj / "src" / "util.py").write_text("def helper() -> int:\n    return 99\n", encoding="utf-8")
    m2 = build_manifest(proj)
    rep2 = gate.evaluate(g, m, m2)
    assert "src/util.py" in rep2.stale["changed"]
    assert rep2.stale_count == 1


def test_store_roundtrip(tmp_path):
    g = build_graph(FIXTURE)
    m = build_manifest(FIXTURE)
    d = store.save(tmp_path, g, m)
    assert (d / "graph.json").is_file() and (d / "manifest.json").is_file()

    g2 = store.load_graph(tmp_path)
    m2 = store.load_manifest(tmp_path)
    assert g2 is not None and m2 is not None
    assert len(g2.nodes) == len(g.nodes)
    assert len(g2.edges) == len(g.edges)
    assert m2 == m
    # broken_refs meta survives the roundtrip
    assert g2.get_node("README.md").meta.get("broken_refs") == ["notes/missing.md"]


def test_corrupt_store_degrades_to_none(tmp_path):
    d = store.store_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "graph.json").write_text("{ not valid json", encoding="utf-8")
    (d / "manifest.json").write_text("also not json", encoding="utf-8")
    assert store.load_graph(tmp_path) is None
    assert store.load_manifest(tmp_path) is None


def test_text_hash_ignores_crlf_vs_lf(tmp_path):
    crlf = tmp_path / "a.md"
    crlf.write_bytes(b"line1\r\nline2\r\n")
    lf = tmp_path / "b.md"
    lf.write_bytes(b"line1\nline2\n")
    assert file_hash(crlf, normalize_newlines=True) == file_hash(lf, normalize_newlines=True)
    assert file_hash(crlf) != file_hash(lf)  # raw mode still distinguishes them


def test_index_single_walk_returns_graph_and_matching_manifest(tmp_path):
    import shutil

    from second_brain.freshness import index

    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    g, m = index(proj)
    file_nodes = {n.id for n in g.nodes.values() if n.path}
    assert set(m) == file_nodes  # manifest and file nodes cover the same files
