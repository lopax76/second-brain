"""v0.6 additions: community-summary query + MCP tool, impact --diff '(none)' explanation,
and per-file node-type overrides via .secondbrain.json."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from second_brain import query
from second_brain.cli import _emit_impact, main
from second_brain.config import _type_overrides, load_config
from second_brain.indexer import build_graph
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _prog(g: Graph, nid: str) -> None:
    g.add_node(Node(id=nid, type=NodeType.PROGRAM, label=nid.split("/")[-1], path=nid))


# --------------------------- community_summary -------------------------------
def test_community_summary_shape_and_determinism():
    g = build_graph(FIXTURE)
    a = query.community_summary(g)
    assert a == query.community_summary(g)            # deterministic
    assert a["count"] == len(a["communities"]) >= 1
    row = a["communities"][0]
    for k in ("name", "size", "key_files", "dominant_types", "cohesion"):
        assert k in row
    assert isinstance(a["surprising_edges"], list)


def test_community_summary_separates_disconnected_modules():
    g = Graph(project="t")
    for nid in ("a1.py", "a2.py", "b1.py", "b2.py"):
        _prog(g, nid)
    g.add_edge(Edge("a1.py", "a2.py", EdgeType.IMPORTS))   # module A
    g.add_edge(Edge("b1.py", "b2.py", EdgeType.IMPORTS))   # module B (disconnected)
    res = query.community_summary(g)
    assert res["count"] >= 2
    assert res["surprising_edges"] == []                   # no cross-module edge


def test_surprising_edges_reports_cross_community_bridge():
    from second_brain import communities
    g = Graph(project="t")
    for nid in ("a.py", "b.py"):
        _prog(g, nid)
    g.add_edge(Edge("a.py", "b.py", EdgeType.IMPORTS))
    se = communities.surprising_edges(g, {"a.py": "A", "b.py": "B"})  # explicit 2 communities
    assert (se[0]["source"], se[0]["target"]) == ("a.py", "b.py")


def test_communities_cli(capsys):
    assert main(["communities", str(FIXTURE)]) == 0
    assert "communities" in capsys.readouterr().out


# --------------------------- impact --diff '(none)' --------------------------
def test_impact_diff_note_when_every_change_is_a_seed():
    g = Graph(project="t")
    for nid in ("a.py", "b.py"):
        _prog(g, nid)
    g.add_edge(Edge("b.py", "a.py", EdgeType.IMPORTS))     # b depends on a
    res = query.impact_diff(g, ["a.py", "b.py"])           # both changed
    assert not res["upstream"] and not res["downstream"]
    assert "note" in res and "among the changed files" in res["note"]


def test_impact_diff_no_note_when_real_impact():
    g = Graph(project="t")
    for nid in ("a.py", "b.py"):
        _prog(g, nid)
    g.add_edge(Edge("b.py", "a.py", EdgeType.IMPORTS))
    res = query.impact_diff(g, ["a.py"])                   # only a changed
    assert res["upstream"]                                 # b surfaces
    assert "note" not in res


def test_emit_impact_empty_hint(capsys):
    _emit_impact("t", {}, False, "every impacted node is already among your changed files")
    assert "(none - every impacted node is already among your changed files)" \
        in capsys.readouterr().out
    _emit_impact("t", {}, False)
    assert "(none)" in capsys.readouterr().out


# --------------------------- type overrides ----------------------------------
def test_type_override_forces_node_type(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "data.json").write_text("{}", encoding="utf-8")          # normally CONFIG
    (proj / ".secondbrain.json").write_text(
        json.dumps({"classify": {"type_overrides": {"data.json": "data"}}}), encoding="utf-8")
    g = build_graph(proj)
    assert g.nodes["data.json"].type is NodeType.DATA


def test_type_override_ignores_unknown_and_area(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    (proj / ".secondbrain.json").write_text(
        json.dumps({"classify": {"type_overrides": {"a.py": "bogus"}}}), encoding="utf-8")
    g = build_graph(proj)
    assert g.nodes["a.py"].type is NodeType.PROGRAM                  # invalid -> heuristic wins


def test_type_override_config_parsing():
    ov = dict(_type_overrides({"./x.py": "DATA", "a\\b.py": "program", 5: "x", "y": ""}))
    assert ov["x.py"] == "data"                                     # ./ stripped, lowercased
    assert ov["a/b.py"] == "program"                               # backslash normalized
    assert "y" not in ov and len(ov) == 2                          # empty/non-str dropped


def test_no_config_means_empty_overrides(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    assert load_config(proj).type_overrides == ()


# --------------------------- MCP server tools --------------------------------
pytest.importorskip("mcp")
from second_brain.mcp_server import build_server  # noqa: E402


def _server(tmp_path):
    dst = tmp_path / "proj"
    shutil.copytree(FIXTURE, dst)                                   # auto-refresh writes here
    return build_server(str(dst))


def _text(server, name, args=None):
    content, _ = asyncio.run(server.call_tool(name, args or {}))
    return content[0].text


def _json(server, name, args=None):
    return json.loads(_text(server, name, args))


def test_mcp_exposes_all_eleven_tools(tmp_path):
    names = {t.name for t in asyncio.run(_server(tmp_path).list_tools())}
    assert names == {"project_map", "find", "neighbors", "subgraph", "impact", "impact_diff",
                     "why", "communities", "focus", "report", "health"}


def test_mcp_every_tool_executes(tmp_path):
    s = _server(tmp_path)
    pm = _json(s, "project_map")
    assert pm["files"] >= 1
    assert _json(s, "communities")["count"] >= 1
    assert _json(s, "find", {"text": "app"})["total"] >= 0
    assert "changed" in _json(s, "impact_diff")
    assert _json(s, "focus", {"task": "app"})["nodes"] is not None
    assert "#" in _text(s, "report")
    assert "status" in _json(s, "health") or "ok" in _json(s, "health")
    node = "src/app.py"
    assert _json(s, "neighbors", {"node_id": node})["id"] == node
    assert "nodes" in _json(s, "subgraph", {"node_id": node})
    assert _json(s, "impact", {"node_id": node}).get("exists")
    assert "exists" in _json(s, "why", {"source": node, "target": "README.md"})


def test_mcp_neighbors_unknown_node(tmp_path):
    assert "error" in _json(_server(tmp_path), "neighbors", {"node_id": "nope.py"})


def test_impact_diff_cli_end_to_end(tmp_path, capsys):
    import subprocess
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "b.py").write_text("import a\n", encoding="utf-8")
    g = {"cwd": str(proj), "check": True}
    subprocess.run(["git", "init", "-q"], **g)
    subprocess.run(["git", "add", "-A"], **g)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "init"], **g)
    assert main(["build", str(proj)]) == 0
    (proj / "a.py").write_text("x = 2\n", encoding="utf-8")   # touch only a -> b is affected
    assert main(["impact", "--diff", str(proj)]) == 0
    assert "working-tree changes" in capsys.readouterr().out


def test_why_cli(capsys):
    rc = main(["why", "src/app.py", "README.md", str(FIXTURE)])
    assert rc == 0                                   # connected or "no path" -> still 0
    assert capsys.readouterr().out                   # something printed
    assert main(["why", "nope.py", "README.md", str(FIXTURE)]) == 1   # unknown node
