"""Tests for documentation reference extraction (links, wikilinks, path-in-prose)."""

from __future__ import annotations

import time

from second_brain.references import extract_references, extract_references_tagged


def test_md_link_regex_no_redos_on_unclosed_runs():
    # A pathological run of unclosed `](` must not blow up (ReDoS): the length-capped regex
    # keeps it linear. 30k repeats finish in well under a second.
    t0 = time.perf_counter()
    extract_references_tagged("](" * 30000)
    assert time.perf_counter() - t0 < 2.0


def test_wikilink_regex_no_redos_on_unclosed_runs():
    # The wikilink regex must also fail fast on a pathological run of unclosed `[[`.
    t0 = time.perf_counter()
    extract_references_tagged("[[" * 200000)
    assert time.perf_counter() - t0 < 2.0


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


def test_single_backtick_example_link_not_extracted():
    # showing markdown-link SYNTAX in a code span is not a real link
    assert extract_references("write `[label](target)` inline") == []


def test_double_backtick_codespan_inner_link_not_extracted():
    # CommonMark: `` `[label](target)` `` is a code span whose inner backticks are literal;
    # the inner link must NOT leak out (regression: CHANGELOG.md -> target).
    assert extract_references("such as `` `[label](target)` `` ok") == []


def test_real_path_in_backticks_is_still_a_reference():
    # a genuine file path in backticks IS a prose reference — the core feature must survive
    assert extract_references("entry point is `src/app.py`") == ["src/app.py"]
