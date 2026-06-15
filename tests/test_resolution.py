"""Conservative reference-resolution: code fragments in docs are not 'broken' file refs."""

from __future__ import annotations

from second_brain.indexer import build_graph


def _broken(graph) -> list[str]:
    out = []
    for n in graph.nodes.values():
        out += n.meta.get("broken_refs", [])
    return out


def test_code_fragment_links_are_not_broken(tmp_path):
    # An HTML doc whose inlined JS yields markdown-link-looking fragments `](A)`, `](g,A)`,
    # `](this.easingTime)` must NOT be reported as broken references.
    (tmp_path / "demo.html").write_text(
        "<script>var x=f](A); y=g](g,A); z=q](this.easingTime);</script>\n",
        encoding="utf-8",
    )
    g = build_graph(tmp_path)
    assert _broken(g) == []


def test_real_missing_file_link_is_still_broken(tmp_path):
    # A genuine internal link to a missing file (has an extension) MUST still be flagged.
    (tmp_path / "README.md").write_text("see [the design](docs/missing.md)\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert "docs/missing.md" in _broken(g)


def test_version_strings_are_not_broken_refs(tmp_path):
    # Regression: markdown links to version/number strings (common in CHANGELOG/release notes)
    # must NOT be reported as broken file references.
    (tmp_path / "CHANGELOG.md").write_text(
        "see [v1.2](v1.2), [1.2.3](1.2.3), and [took 2.36s](2.36s)\n", encoding="utf-8"
    )
    g = build_graph(tmp_path)
    assert _broken(g) == []


def test_existing_asset_link_not_broken(tmp_path):
    # A link to a real non-indexed asset (image) is not broken (regression guard).
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "README.md").write_text("![logo](img.png)\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert _broken(g) == []
