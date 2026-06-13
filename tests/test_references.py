"""Tests for documentation reference extraction (links, wikilinks, path-in-prose)."""

from __future__ import annotations

from second_brain.references import extract_references


def test_markdown_link():
    assert extract_references("see [the guide](docs/guide.md) now") == ["docs/guide.md"]


def test_wikilink_with_alias_and_anchor_stripped():
    assert extract_references("[[README|home]] and [[Notes#section]]") == ["README", "Notes"]


def test_plain_path_in_prose():
    refs = extract_references("the entry point is src/app.py, see also config.toml")
    assert "src/app.py" in refs
    assert "config.toml" in refs


def test_urls_are_ignored():
    refs = extract_references("link [x](https://example.com/a.html) and http://y.io/b.md")
    assert refs == []


def test_anchor_and_query_stripped_from_links():
    assert extract_references("[a](docs/guide.md#intro?x=1)") == ["docs/guide.md"]


def test_dedup_preserves_order():
    text = "src/app.py then [app](src/app.py) and src/app.py again, plus util.py"
    assert extract_references(text) == ["src/app.py", "util.py"]


def test_backslash_paths_normalized():
    assert extract_references(r"see src\pkg\mod.py here") == ["src/pkg/mod.py"]
