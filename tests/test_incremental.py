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
    import second_brain

    _seed(tmp_path)
    _incremental(tmp_path)
    p = tmp_path / ".secondbrain" / "extract.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    # A well-formed identity from a FUTURE shape. Writing the bare integer `CACHE_VERSION + 1`
    # only proved "a value of the wrong type is refused", since cache_id() is now a string.
    data["version"] = f"{CACHE_VERSION + 1}-{second_brain.__version__}"
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
    (tmp_path / "aaaa.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "zzzz.py").write_text("Z = 1\n", encoding="utf-8")
    # Isometric targets, ASSERTED: with "alpha.py" vs "zeta.py" the two versions differed by one
    # byte, so the size in the coarse stamp invalidated the cache on its own and this test proved
    # nothing. Keep the assertion so the premise cannot go quietly false again.
    v1 = f"[link](aaaa.py)\n{filler}"
    v2 = f"[link](zzzz.py)\n{filler}"
    assert len(v1) == len(v2)

    big = tmp_path / "big.md"
    big.write_text(v1, encoding="utf-8")
    _incremental(tmp_path)

    # Same byte length, different target, written immediately (same whole second).
    big.write_text(v2, encoding="utf-8")
    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)
    assert any(
        e["source"] == "big.md" and e["target"] == "zzzz.py" for e in json.loads(got)["edges"]
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


def test_a_change_between_reads_cannot_mislabel_the_cache(tmp_path, monkeypatch):
    """The window a revert-between-builds can never reach.

    0.9.2 took the digest and the findings from two separate reads, so a file rewritten in between
    was stored as "digest of one version, findings of another". Because it then settled on the
    version that had been digested, every later build matched the cache and served the wrong
    findings — permanently, with ``gate`` green. Only exercising that window catches it: this test
    passes on a single read and fails the moment a second one is reintroduced.
    """
    import second_brain.freshness as fr

    for name in ("alpha", "bbbbb"):
        (tmp_path / f"{name}.py").write_text("X = 1\n", encoding="utf-8")
    doc = tmp_path / "doc.md"
    v1, v2 = "[x](alpha.py)\n", "[x](bbbbb.py)\n"
    assert len(v1) == len(v2)  # isometric on purpose: the manifest stamp must not rescue us

    doc.write_text(v1, encoding="utf-8")
    real_read = fr.read_bytes_capped
    swapped: list[bool] = []

    def read_then_swap(path):
        data = real_read(path)
        if path.name == "doc.md" and not swapped:
            swapped.append(True)
            doc.write_text(v2, encoding="utf-8")  # the file moves AFTER this read
        return data

    monkeypatch.setattr(fr, "read_bytes_capped", read_then_swap)
    _incremental(tmp_path)
    monkeypatch.undo()

    assert swapped, "the window was never exercised — the test would prove nothing"
    assert doc.read_text(encoding="utf-8") == v2

    got, _ = _incremental(tmp_path)
    assert got == _full(tmp_path)
    got_again, _ = _incremental(tmp_path)
    assert got_again == _full(tmp_path)  # and the disagreement is not permanent


def test_reverting_a_file_serves_its_own_findings_not_the_other_version(tmp_path):
    """The label on a cache entry must describe the bytes the findings came from.

    This is what made the mid-build race permanent: the digest and the extraction were taken from
    two separate reads, so an entry could end up keyed by version X while holding version Y's
    findings. It stayed wrong forever, because the file had settled on X and every later build
    recomputed X and matched. Reverting content is the shortest way to catch a mislabelled entry.
    """
    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "zeta.py").write_text("Z = 1\n", encoding="utf-8")
    doc = tmp_path / "doc.md"

    doc.write_text("[x](alpha.py)\n", encoding="utf-8")
    _incremental(tmp_path)
    doc.write_text("[x](zeta.py)\n", encoding="utf-8")
    _incremental(tmp_path)
    doc.write_text("[x](alpha.py)\n", encoding="utf-8")  # back to the first version
    got, _ = _incremental(tmp_path)

    assert got == _full(tmp_path)
    edges = [e for e in json.loads(got)["edges"] if e["source"] == "doc.md"]
    assert any(e["target"] == "alpha.py" for e in edges)
    assert not any(e["target"] == "zeta.py" for e in edges)


def test_a_file_that_vanishes_after_the_walk_is_not_a_node(tmp_path):
    """Regression: a phantom node used to survive every rebuild with ``gate`` green.

    ``rels`` is fixed by the walk, and a node was created for every entry whether or not the file
    still existed. Such a file was absent from both the signature and the manifest, so the next
    walk could not see any change and nothing ever removed it.
    """
    import second_brain.freshness as fr

    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    real_iter = fr.iter_files

    def iter_with_phantom(root, patterns, git_rules=None):
        return sorted([*real_iter(root, patterns, git_rules), "ghost.py"])

    fr.iter_files = iter_with_phantom
    try:
        res = index_cached(tmp_path, operational=False)
    finally:
        fr.iter_files = real_iter

    assert "ghost.py" not in res.graph.nodes
    assert "ghost.py" not in res.manifest
    assert "ghost.py" not in res.signature


def test_an_entry_that_exists_but_cannot_be_stat_ed_stays_a_node(tmp_path):
    """A dangling symlink is a real directory entry, and things link to it.

    Regression: the phantom-node fix first dropped every file whose ``stat`` failed, conflating
    "deleted between the walk and now" with "exists but cannot be followed". A git clone of a
    symlinked ``AGENTS.md`` leaves exactly the latter on Windows — and dropping the node silently
    turned every reference to it into a broken one.
    """
    import pathlib

    (tmp_path / "doc.md").write_text("[a](AGENTS.md)\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# agents\n", encoding="utf-8")

    real_stat = pathlib.Path.stat

    def stat_that_fails_on_agents(self, *a, **k):
        if self.name == "AGENTS.md":
            raise OSError("simulated dangling link")
        return real_stat(self, *a, **k)

    pathlib.Path.stat = stat_that_fails_on_agents
    try:
        res = index_cached(tmp_path, operational=False)
    finally:
        pathlib.Path.stat = real_stat

    from second_brain.freshness import UNREADABLE

    assert "AGENTS.md" in res.graph.nodes  # still a node...
    # ...and the signature records that it could not be read, rather than omitting it. Omitting it
    # made a fresh signature agree with the stored one (both silent), so the lost edges stuck for
    # good; the sentinel differs from any real value, so the file is retried once it can be read.
    assert res.signature["AGENTS.md"] == UNREADABLE
    doc = res.graph.nodes["doc.md"]
    assert "broken_refs" not in doc.meta  # so the reference to it still resolves


def test_cache_is_invalidated_by_a_new_second_brain_version(tmp_path):
    """A release that changes what an extractor finds must not serve the old findings."""
    import second_brain
    from second_brain.extract import cache_id

    _seed(tmp_path)
    _incremental(tmp_path)
    assert store.load_extract(tmp_path)  # populated under the current identity

    original = second_brain.__version__
    second_brain.__version__ = f"{original}-next"
    try:
        assert cache_id().endswith("-next")
        assert store.load_extract(tmp_path) == {}  # stored under the old identity: refused
        _, stats = _incremental(tmp_path)
        assert stats["reused"] == 0
    finally:
        second_brain.__version__ = original


def test_poisoned_entry_types_are_refused_not_crashed_on(tmp_path):
    """A well-shaped entry holding wrong types used to explode inside reference resolution."""
    _seed(tmp_path)
    _incremental(tmp_path)
    p = tmp_path / ".secondbrain" / "extract.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    good = data["files"]["doc.md"]["h"]
    data["files"]["doc.md"] = {"h": good, "r": [[999, "link"]]}          # numeric target
    data["files"]["app.py"]["p"] = [[0, ["not", "a", "string"], []]]      # list where str belongs
    p.write_text(json.dumps(data), encoding="utf-8")

    got, _ = _incremental(tmp_path)  # must not raise
    assert got == _full(tmp_path)


def test_deeply_nested_store_does_not_crash_the_build(tmp_path):
    """RecursionError is a RuntimeError, not a ValueError: it used to escape the store guard."""
    _seed(tmp_path)
    _incremental(tmp_path)
    p = tmp_path / ".secondbrain" / "extract.json"
    p.write_text("[" * 20000 + "]" * 20000, encoding="utf-8")

    assert store.load_extract(tmp_path) == {}
    got, _ = _incremental(tmp_path)  # must not raise
    assert got == _full(tmp_path)


def test_large_text_file_keeps_incremental_equal_to_full(tmp_path):
    """Files above the content-hash cap are keyed on the precise signature, not the coarse stamp."""
    filler = "y" * 2_000_000  # over the 1 MB hash cap, under the 5 MB read cap
    (tmp_path / "aaaa.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "zzzz.py").write_text("Z = 1\n", encoding="utf-8")
    v1 = f"[l](aaaa.py)\n{filler}"
    v2 = f"[l](zzzz.py)\n{filler}"
    assert len(v1) == len(v2)  # see the note in the test above

    big = tmp_path / "big.md"
    big.write_text(v1, encoding="utf-8")
    _incremental(tmp_path)
    big.write_text(v2, encoding="utf-8")
    got, _ = _incremental(tmp_path)

    assert got == _full(tmp_path)
    assert any(
        e["source"] == "big.md" and e["target"] == "zzzz.py" for e in json.loads(got)["edges"]
    )


def test_changing_secondbrain_json_makes_the_project_stale(tmp_path, monkeypatch):
    """SB's own config is an input to the graph, so it belongs in the freshness signature.

    ``.secondbrain.json`` is excluded from the walk, so editing it used to leave a stale graph that
    reported itself fresh — `is_stale` False, `gate` green — for every subsequent query.
    """
    import second_brain.freshness as fr
    from second_brain.model import NodeType

    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    (tmp_path / "note.md").write_text("# note\n", encoding="utf-8")
    first = fr.load_or_refresh(tmp_path)
    assert first.nodes["note.md"].type is not NodeType.DECISION

    (tmp_path / ".secondbrain.json").write_text(
        '{"classify": {"type_overrides": {"note.md": "decision"}}}', encoding="utf-8"
    )
    assert fr.is_stale(tmp_path) is True
    assert fr.load_or_refresh(tmp_path).nodes["note.md"].type is NodeType.DECISION


def test_an_unreadable_file_is_retried_once_it_can_be_read(tmp_path):
    """A momentary lock must not cost a file its edges permanently.

    Both a stored and a fresh signature used to omit an unreadable file, so they agreed and nothing
    ever retried it: its edges were gone for good. The sentinel differs from any real value.
    """
    import pathlib

    import second_brain.freshness as fr

    (tmp_path / "doc.md").write_text("[a](target.md)\n", encoding="utf-8")
    (tmp_path / "target.md").write_text("# t\n", encoding="utf-8")

    real_read = pathlib.Path.read_bytes

    def refuse_doc(self, *a, **k):
        if self.name == "doc.md":
            raise OSError("locked by another process")
        return real_read(self, *a, **k)

    pathlib.Path.read_bytes = refuse_doc
    try:
        locked = index_cached(tmp_path, operational=False)
    finally:
        pathlib.Path.read_bytes = real_read

    assert locked.signature["doc.md"] == fr.UNREADABLE
    assert not any(e.source == "doc.md" and e.target == "target.md" for e in locked.graph.edges)

    # Now readable: the sentinel no longer matches, so the file is re-read and its edge comes back.
    recovered = index_cached(tmp_path, operational=False)
    assert recovered.signature["doc.md"] != fr.UNREADABLE
    assert any(e.source == "doc.md" and e.target == "target.md" for e in recovered.graph.edges)


def test_fast_signature_also_marks_an_unreadable_file(tmp_path):
    """Both sides of the comparison must use the sentinel, or the retry never happens.

    ``is_stale`` compares a stored signature with a fresh one. If ``index_cached`` records the
    sentinel but ``fast_signature`` omits the file, the two differ for ever and the project is
    permanently stale; if both omit it, they agree and the lost edges never come back. Only the two
    agreeing on the sentinel gives the wanted behaviour — stable while locked, retried when freed.
    """
    import pathlib

    import second_brain.freshness as fr

    (tmp_path / "doc.md").write_text("# d\n", encoding="utf-8")
    real_stat = pathlib.Path.stat

    def refuse_doc(self, *a, **k):
        if self.name == "doc.md":
            raise OSError("locked")
        return real_stat(self, *a, **k)

    pathlib.Path.stat = refuse_doc
    try:
        sig = fr.fast_signature(tmp_path)
    finally:
        pathlib.Path.stat = real_stat

    assert sig["doc.md"] == fr.UNREADABLE


def test_the_coarse_stamp_distinguishes_writes_within_one_second(tmp_path):
    """Above the cap the manifest value must carry nanoseconds, not whole seconds.

    With ``m{int(st.st_mtime)}`` two different contents of the same length written inside one
    second produced the SAME manifest value — and `gate` recomputes exactly that value, so it
    reported clean over a changed file.
    """
    from second_brain.freshness import _hash_rel

    big = tmp_path / "big.md"
    filler = "z" * 1_200_000  # above the content-hash cap: stamp, not digest
    big.write_text(f"aaaa{filler}", encoding="utf-8")
    first = _hash_rel(tmp_path, "big.md")
    big.write_text(f"bbbb{filler}", encoding="utf-8")  # same length, same second
    second = _hash_rel(tmp_path, "big.md")

    assert first is not None and second is not None
    assert first.startswith("s") and ":m" in first  # it really is the stamp branch
    assert first != second


def test_gate_declares_which_files_it_could_only_check_by_stamp(tmp_path):
    """Above the content-hash cap `gate` compares a stat stamp, not content. It must say so."""
    from second_brain import gate
    from second_brain.freshness import build_manifest

    (tmp_path / "small.md") .write_text("# s\n", encoding="utf-8")
    (tmp_path / "big.md").write_text("y" * 1_200_000, encoding="utf-8")
    res = index_cached(tmp_path, operational=False)
    rep = gate.evaluate(res.graph, res.manifest, build_manifest(tmp_path))

    assert "big.md" in rep.stamp_only
    assert "small.md" not in rep.stamp_only
    assert "size+mtime only" in rep.summary()


def test_full_flag_ignores_the_cache(tmp_path):
    _seed(tmp_path)
    _incremental(tmp_path)
    stats: dict[str, int] = {}
    index_cached(tmp_path, operational=False, incremental=False, stats=stats)
    assert stats["reused"] == 0
