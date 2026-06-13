"""Indexer tests against the synthetic fixture (known ground truth)."""

from __future__ import annotations

from pathlib import Path

from second_brain.indexer import build_graph
from second_brain.model import EdgeType, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _g():
    return build_graph(FIXTURE)


def _edges(g, etype):
    return {(e.source, e.target) for e in g.edges if e.type is etype}


def test_project_name():
    assert _g().project == "sample_project"


def test_node_types_classified():
    g = _g()
    expect = {
        "README.md": NodeType.STRUCTURE,
        "config.toml": NodeType.CONFIG,
        "src/app.py": NodeType.PROGRAM,
        "src/util.py": NodeType.PROGRAM,
        "src/__init__.py": NodeType.PROGRAM,
        "docs/guide.md": NodeType.STRUCTURE,  # loose doc -> structure fallback
        "data/store.csv": NodeType.DATA,
        "notes/report-2026-01-01.md": NodeType.REPORT,
    }
    for nid, nt in expect.items():
        assert g.get_node(nid) is not None, f"missing node {nid}"
        assert g.get_node(nid).type is nt, f"{nid} -> {g.get_node(nid).type} != {nt}"


def test_areas_and_membership():
    g = _g()
    for area in ("area:src", "area:docs", "area:data", "area:notes", "area:(root)"):
        assert g.get_node(area) is not None and g.get_node(area).type is NodeType.AREA
    belongs = _edges(g, EdgeType.BELONGS_TO)
    assert ("src/app.py", "area:src") in belongs
    assert ("README.md", "area:(root)") in belongs
    assert ("data/store.csv", "area:data") in belongs


def test_python_import_edge():
    imports = _edges(_g(), EdgeType.IMPORTS)
    assert ("src/app.py", "src/util.py") in imports
    # no spurious edge to the package __init__
    assert ("src/app.py", "src/__init__.py") not in imports


def test_reference_edges():
    refs = _edges(_g(), EdgeType.REFERENCES)
    assert ("README.md", "docs/guide.md") in refs       # markdown link
    assert ("README.md", "src/app.py") in refs          # path-in-prose
    assert ("README.md", "notes/report-2026-01-01.md") in refs
    assert ("docs/guide.md", "README.md") in refs        # wikilink resolved by stem


def test_broken_reference_recorded():
    g = _g()
    # The dead markdown link is broken; the plain prose example is NOT.
    assert g.get_node("README.md").meta.get("broken_refs") == ["notes/missing.md"]


def test_prose_example_is_not_broken():
    g = _g()
    broken = g.get_node("README.md").meta.get("broken_refs") or []
    assert "example/ghost.md" not in broken


def test_external_url_not_a_reference():
    refs = _edges(_g(), EdgeType.REFERENCES)
    assert all("example.com" not in t for _, t in refs)


def test_descriptions_present():
    g = _g()
    assert g.get_node("src/util.py").description.startswith("program")
    # util.py is imported by app.py -> 1 inbound
    assert "1 inbound" in g.get_node("src/util.py").description


def test_code_files_do_not_emit_doc_references(tmp_path):
    # Filename-looking strings inside source code must NOT become references/broken.
    (tmp_path / "mod.py").write_text(
        'PATHS = ["docs/missing.md", "other/ghost.md"]\n# see also notes/x.md\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("entry point: mod.py\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert g.get_node("mod.py").meta.get("broken_refs") is None
    refs = {(e.source, e.target) for e in g.edges if e.type is EdgeType.REFERENCES}
    assert not any(s == "mod.py" for s, _ in refs)
    assert ("README.md", "mod.py") in refs  # the doc legitimately references the file


def test_reference_into_ignored_dir_is_not_broken(tmp_path):
    (tmp_path / "README.md").write_text("vendored at node_modules/foo.js\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert g.get_node("README.md").meta.get("broken_refs") is None


def test_relative_import_above_root_yields_no_edge(tmp_path):
    # `from .. import x` in a root-level module is illegal -> no edge, no crash.
    (tmp_path / "mod.py").write_text("from .. import sibling\n", encoding="utf-8")
    (tmp_path / "sibling.py").write_text("x = 1\n", encoding="utf-8")
    g = build_graph(tmp_path)
    imports = {(e.source, e.target) for e in g.edges if e.type is EdgeType.IMPORTS}
    assert imports == set()


def test_extensionless_internal_link_is_broken(tmp_path):
    (tmp_path / "README.md").write_text("dead: [old](notes/missing)\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert g.get_node("README.md").meta.get("broken_refs") == ["notes/missing"]


def test_bare_concept_wikilink_is_not_broken(tmp_path):
    (tmp_path / "README.md").write_text("see [[SomeConcept]]\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert g.get_node("README.md").meta.get("broken_refs") is None

def test_file_nodes_record_on_disk_size(tmp_path):
    (tmp_path / "a.md").write_bytes(b"hello world\n")
    g = build_graph(tmp_path)
    assert g.get_node("a.md").meta.get("size") == 12
