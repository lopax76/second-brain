"""Incremental indexing: the result must be indistinguishable from a full rebuild.

The whole design rests on one property — extraction is cached per file, resolution is redone
globally every time — so these tests attack precisely the cases where a naive incremental
updater would leave a stale cross-file edge behind: a file appearing, a file disappearing, and
a reference in a document that itself never changed.
"""

from __future__ import annotations

import json

from second_brain import store
from second_brain.extract import CACHE_VERSION, FileExtract, extract_file, is_extractable
from second_brain.freshness import index_cached
from second_brain.indexer import build_graph


def _full(root) -> str:
    """A from-scratch graph, serialized — the reference answer."""
    return build_graph(root).to_json()


def _incremental(root) -> tuple[str, dict[str, int]]:
    """Rebuild through the cached path, persisting the store like a real build does."""
    stats: dict[str, int] = {}
    res = index_cached(root, operational=False, stats=stats)
    store.save(root, res.graph, res.manifest, signature=res.signature, symbols=False,
               extract=res.extract)
    return res.graph.to_json(), stats


def _seed(tmp_path) -> None:
    (tmp_path / "doc.md").write_text(
        "See [code](app.py) and [missing](gone.py).\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")


def test_incremental_matches_full_after_edit(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    (tmp_path / "app.py").write_text("import helper\nimport os\n", encoding="utf-8")
    got, stats = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert stats["reused"] > 0  # unchanged files really were skipped


def test_added_file_updates_an_unchanged_document(tmp_path):
    """The cross-file case a naive cache gets wrong.

    ``doc.md`` links to ``gone.py``, which does not exist -> broken reference. Creating that
    file must make the link resolve, even though ``doc.md`` itself never changed and is served
    entirely from cache.
    """
    _seed(tmp_path)
    first, _ = _incremental(tmp_path)
    doc_before = next(n for n in json.loads(first)["nodes"] if n["id"] == "doc.md")
    assert "gone.py" in doc_before["meta"].get("broken_refs", [])  # premise: it starts broken

    (tmp_path / "gone.py").write_text("X = 1\n", encoding="utf-8")
    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)

    data = json.loads(got)
    doc = next(n for n in data["nodes"] if n["id"] == "doc.md")
    assert "broken_refs" not in doc["meta"]  # the link now resolves
    assert any(e for e in data["edges"] if e["source"] == "doc.md" and e["target"] == "gone.py")


def test_removed_file_breaks_a_reference_from_an_unchanged_document(tmp_path):
    """The mirror case: deleting a target must break the link in a document served from cache."""
    _seed(tmp_path)
    _incremental(tmp_path)
    (tmp_path / "app.py").unlink()
    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)

    doc = next(n for n in json.loads(got)["nodes"] if n["id"] == "doc.md")
    assert "app.py" in doc["meta"].get("broken_refs", [])


def test_removed_file_drops_its_import_edges(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    (tmp_path / "helper.py").unlink()
    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert not any(e["target"] == "helper.py" for e in json.loads(got)["edges"])


def test_corrupt_cache_falls_back_to_a_correct_full_build(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    (tmp_path / ".secondbrain" / "extract.json").write_text("{not json", encoding="utf-8")
    got, stats = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert stats["reused"] == 0  # nothing was trusted


def test_cache_from_a_future_version_is_ignored(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    p = tmp_path / ".secondbrain" / "extract.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["version"] = CACHE_VERSION + 1
    p.write_text(json.dumps(data), encoding="utf-8")
    got, stats = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert stats["reused"] == 0


def test_tampered_cache_entry_does_not_survive_a_content_change(tmp_path):
    """A cache entry is only trusted when its hash matches the file's current content."""
    _seed(tmp_path)
    _incremental(tmp_path)
    p = tmp_path / ".secondbrain" / "extract.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["files"]["app.py"]["p"] = [[0, "totally_made_up", []]]  # lie about app.py's imports
    p.write_text(json.dumps(data), encoding="utf-8")

    # Same content -> the lie IS served (that is the contract: hash matches, entry trusted)...
    got, _ = _incremental(tmp_path)
    assert got != _full(tmp_path)
    # ...but the moment the file actually changes, the hash moves and the truth comes back.
    (tmp_path / "app.py").write_text("import helper\n# touched\n", encoding="utf-8")
    got2, _ = _incremental(tmp_path)
    assert got2 == _full(tmp_path)


def test_symbols_build_does_not_reuse_a_symbol_less_cache(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)  # cached without symbols
    stats: dict[str, int] = {}
    res = index_cached(tmp_path, operational=False, symbols=True, stats=stats)
    assert stats["reused"] == 0  # every extractable file re-read for the symbol layer
    assert res.graph.to_json() == build_graph(tmp_path, symbols=True).to_json()


def test_non_extractable_files_are_never_cached(tmp_path):
    _seed(tmp_path)
    (tmp_path / "data.json").write_text('{"a": 1}', encoding="utf-8")
    _incremental(tmp_path)
    cached = store.load_extract(tmp_path)
    assert "data.json" not in cached  # config/data is never opened, so nothing to remember
    assert "app.py" in cached
    assert not is_extractable("data.json")


def test_extract_roundtrip_preserves_findings(tmp_path):
    (tmp_path / "m.md").write_text("[a](x.py) and `y/z.md`\n", encoding="utf-8")
    fe = extract_file(tmp_path, "m.md")
    assert fe is not None and fe.refs
    assert FileExtract.from_json(fe.to_json()) == fe


def test_large_file_same_size_same_second_is_not_served_from_cache(tmp_path):
    """Regression: a file above the content-hash cap must not be keyed on size+second mtime.

    The manifest stores ``s<size>:m<seconds>`` for files over 1 MB. Rewriting such a file to the
    same length within the same second leaves that stamp untouched — so keying the extraction
    cache on it reused the previous parse and produced a graph that a full rebuild disagreed
    with, invisibly to ``gate`` (which recomputes the very same stamp).
    """
    filler = "x" * 1_100_000
    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "zeta.py").write_text("Z = 1\n", encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_text(f"[link](alpha.py)\n{filler}", encoding="utf-8")
    _incremental(tmp_path)

    # Same byte length, different target, written immediately (same whole second).
    big.write_text(f"[link](zeta.py)\n{filler}", encoding="utf-8")
    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert any(
        e["source"] == "big.md" and e["target"] == "zeta.py" for e in json.loads(got)["edges"]
    )


def test_a_drifted_store_heals_on_the_next_build(tmp_path):
    """Regression: an incremental rebuild must be able to CORRECT the store, not re-confirm it.

    When the manifest hash was carried over on an unchanged size+mtime, a store that had drifted
    stayed wrong for every subsequent build — the stale hash validated the stale cache entry,
    which regenerated the stale hash. ``gate`` said DRIFT while rebuilding changed nothing.
    """
    import os

    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "bravo.py").write_text("B = 1\n", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text("[x](alpha.py)\n", encoding="utf-8")
    _incremental(tmp_path)
    before = doc.stat()

    # Same size, and mtime forced back to exactly what it was: the cheap signature cannot tell.
    doc.write_text("[x](bravo.py)\n", encoding="utf-8")
    os.utime(doc, ns=(before.st_atime_ns, before.st_mtime_ns))

    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)  # one plain rebuild is enough to heal it
    assert any(
        e["source"] == "doc.md" and e["target"] == "bravo.py" for e in json.loads(got)["edges"]
    )


def test_full_flag_ignores_the_cache(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    stats: dict[str, int] = {}
    index_cached(tmp_path, operational=False, incremental=False, stats=stats)
    assert stats["reused"] == 0
