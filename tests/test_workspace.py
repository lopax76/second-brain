"""0.10: the workspace hierarchy — one graph per project, a superior graph linking everything."""

from __future__ import annotations

import json
import subprocess
import sys

from second_brain import freshness, lock, store, workspace
from second_brain.model import NodeType


def _ws(tmp_path):
    root = tmp_path / "Documents"
    mem = tmp_path / "home" / ".claude" / "projects"
    (root / "Alfa" / "src").mkdir(parents=True)
    (root / "Alfa" / "PROGETTO.md").write_text(
        "# Alfa\nUsa le note di [Beta](../Beta/README.md) e [regole](../Note/regole.md).\n",
        encoding="utf-8")
    (root / "Alfa" / "src" / "main.py").write_text("import os\n", encoding="utf-8")
    (root / "Beta").mkdir()
    (root / "Beta" / ".git").mkdir()
    (root / "Beta" / "README.md").write_text("# Beta\n", encoding="utf-8")
    (root / "Note").mkdir()
    (root / "Note" / "regole.md").write_text(
        "# Regole\nVedi [Alfa](../Alfa/PROGETTO.md).\n", encoding="utf-8")
    (root / "indice.md").write_text("# Indice\n- [regole](Note/regole.md)\n", encoding="utf-8")
    # a Claude Code memory folder for project Alfa, and one memory citing Beta
    from second_brain.superiore import _claude_key  # the folder name is the encoded path
    mdir = mem / _claude_key((root / "Alfa").resolve()) / "memory"
    mdir.mkdir(parents=True)
    (mdir / "fatto.md").write_text(
        f"---\ntype: project\n---\nIl codice sta in {(root / 'Beta' / 'README.md').as_posix()}\n"
        f"e le regole in `{root / 'Note' / 'regole.md'}`.\n",
        encoding="utf-8")
    (root / workspace.WORKSPACE_FILE).write_text(json.dumps({
        "progetti": "auto", "memorie": [str(mem / "*" / "memory" / "*.md")]}), encoding="utf-8")
    return root


def test_projects_are_detected_and_get_their_own_store(tmp_path):
    root = _ws(tmp_path)
    ws = workspace.find_workspace(root)
    assert ws is not None
    assert [p.rel for p in ws.projects] == ["Alfa", "Beta"]  # Note has no marker: general memory
    assert store.store_dir(root / "Alfa") == root / ".secondbrain" / "progetti" / "alfa"
    assert store.store_dir(root) == root / ".secondbrain" / "superiore"
    assert not (root / "Alfa" / ".secondbrain").exists()


def test_the_superior_graph_holds_general_files_projects_and_memories(tmp_path):
    root = _ws(tmp_path)
    freshness.load_or_refresh(root / "Alfa")
    freshness.load_or_refresh(root / "Beta")
    sup = freshness.load_or_refresh(root)

    ids = set(sup.nodes)
    assert "indice.md" in ids and "Note/regole.md" in ids          # general memory
    assert not any(i.startswith("Alfa/") or i.startswith("Beta/") for i in ids)  # not swallowed
    assert sup.nodes["progetto:alfa"].type is NodeType.PROJECT
    assert sup.nodes["progetto:alfa"].meta["files"] == 2
    mem = [n for n in sup.nodes.values()
           if n.type is NodeType.MEMORY and n.id.startswith("memoria:")]
    assert len(mem) == 1

    edges = {(e.source, e.target) for e in sup.edges}
    assert ("Note/regole.md", "progetto:alfa") in edges         # general file -> project
    assert ("progetto:alfa", "progetto:beta") in edges          # project -> project
    assert ("progetto:alfa", "Note/regole.md") in edges         # project -> general file
    assert (mem[0].id, "progetto:alfa") in edges                # memory belongs to its project
    assert (mem[0].id, "progetto:beta") in edges                # memory cites another project
    assert (mem[0].id, "Note/regole.md") in edges               # backticked path in a memory
    assert "broken_refs" not in sup.nodes["Note/regole.md"].meta  # resolved, not "broken"


def test_rebuilding_one_project_never_rewrites_another(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    root = _ws(tmp_path)
    freshness.load_or_refresh(root / "Alfa")
    freshness.load_or_refresh(root / "Beta")
    beta_graph = store.store_dir(root / "Beta") / "graph.json"
    before = beta_graph.stat().st_mtime_ns
    (root / "Alfa" / "nuovo.md").write_text("# nuovo\n", encoding="utf-8")
    g = freshness.load_or_refresh(root / "Alfa", refresh=True)
    assert "nuovo.md" in g.nodes
    assert beta_graph.stat().st_mtime_ns == before


def test_a_locked_project_does_not_block_another_project(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    root = _ws(tmp_path)
    freshness.load_or_refresh(root / "Alfa")
    freshness.load_or_refresh(root / "Beta")
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys\nfrom second_brain import lock\n"
         "with lock.write_lock(sys.argv[1]):\n    print('preso', flush=True); sys.stdin.read()",
         str(store.store_dir(root / "Alfa"))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "preso"
        (root / "Beta" / "altro.md").write_text("# altro\n", encoding="utf-8")
        g = freshness.load_or_refresh(root / "Beta", refresh=True)
        assert "altro.md" in g.nodes and freshness.last_problem is None
        (root / "Alfa" / "x.md").write_text("# x\n", encoding="utf-8")
        freshness.load_or_refresh(root / "Alfa", refresh=True)
        assert freshness.last_problem and freshness.last_problem["kind"] == "busy"
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=30)
    with lock.write_lock(store.store_dir(root / "Alfa")):
        pass


def test_the_superior_graph_goes_stale_when_a_project_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    root = _ws(tmp_path)
    freshness.load_or_refresh(root / "Alfa")
    freshness.load_or_refresh(root)
    assert not freshness.is_stale(root)
    (root / "Alfa" / "y.md").write_text("# y\n", encoding="utf-8")
    freshness.load_or_refresh(root / "Alfa", refresh=True)   # Alfa's summary changes
    assert freshness.is_stale(root)                          # ... so the superior must refresh
    sup = freshness.load_or_refresh(root, refresh=True)
    assert sup.nodes["progetto:alfa"].meta["files"] == 3


def test_memory_paths_are_found_in_windows_and_posix_form():
    from second_brain.superiore import _code_paths
    text = ("Il codice sta in C:/Users/x/Documents/Beta/README.md e in /home/x/Docs/Beta/a.md.\n"
            r"Vedi anche `Note\regole.md` ma non https://example.com/a/b ne' /api." "\n")
    found = _code_paths(text)
    assert "C:/Users/x/Documents/Beta/README.md" in found
    assert "/home/x/Docs/Beta/a.md" in found
    assert r"Note\regole.md" in found
    assert not any("example.com" in f for f in found) and "/api" not in found
