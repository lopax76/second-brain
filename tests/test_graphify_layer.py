"""0.10: graphify's code graph read as the code layer (cross-file relations, fresh only)."""

from __future__ import annotations

import json
import os
import time

from second_brain import freshness


def _project(tmp_path, *, graph_age: float = 0.0):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Game.cs").write_text("class Game { void Run() { new Player().Move(); } }\n",
                                 encoding="utf-8")
    (src / "Player.cs").write_text("class Player { public void Move() {} }\n", encoding="utf-8")
    old = time.time() - 600
    for f in ("Game.cs", "Player.cs"):
        os.utime(src / f, (old, old))
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps({
        "directed": True, "multigraph": False, "graph": {},
        "nodes": [
            {"id": "game", "label": "Game.cs", "source_file": "src/Game.cs"},
            {"id": "game_run", "label": "Run", "source_file": "src/Game.cs"},
            {"id": "player", "label": "Player.cs", "source_file": "src/Player.cs"},
            {"id": "player_move", "label": "Move", "source_file": "src/Player.cs"},
        ],
        "links": [
            {"source": "game_run", "target": "player_move", "relation": "calls",
             "confidence": "EXTRACTED"},
            {"source": "game", "target": "game_run", "relation": "contains",
             "confidence": "EXTRACTED"},
        ]}), encoding="utf-8")
    t = time.time() - graph_age
    os.utime(out / "graph.json", (t, t))
    return tmp_path


def test_cross_file_calls_become_edges_with_provenance(tmp_path):
    root = _project(tmp_path)
    g = freshness.index_cached(root, operational=False).graph
    edges = [e for e in g.edges if e.meta.get("via") == "graphify"]
    assert [(e.source, e.target, e.type.value) for e in edges] == [
        ("src/Game.cs", "src/Player.cs", "imports")]
    assert edges[0].meta["relation"] == "calls" and edges[0].meta["confidence"] == "EXTRACTED"
    assert "graphify-out/graph.json" not in g.nodes  # graphify's output is not indexed as a file


def test_a_relation_older_than_its_files_is_not_imported(tmp_path):
    root = _project(tmp_path, graph_age=3600)   # graphify ran BEFORE the files last changed
    g = freshness.index_cached(root, operational=False).graph
    assert not [e for e in g.edges if e.meta.get("via") == "graphify"]


def test_a_new_graphify_run_makes_the_project_graph_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    root = _project(tmp_path)
    freshness.load_or_refresh(root)
    assert not freshness.is_stale(root)
    gj = root / "graphify-out" / "graph.json"
    gj.write_text(gj.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert freshness.is_stale(root)
