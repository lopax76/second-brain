"""0.10.3: backup copies and logs stay in the graph but no longer crowd out the answer."""

from __future__ import annotations

from second_brain import freshness, query
from second_brain.classify import classify, copy_original, is_copy_or_log
from second_brain.model import Edge, EdgeType, Graph, Node, NodeType


def test_backup_copies_are_recognised_and_take_the_original_type():
    assert copy_original("maestro-backup-tray.pyw.bak-20260718-1835") == "maestro-backup-tray.pyw"
    assert copy_original("maestro-backup-nas.ps1.bak.20260610-093835") == "maestro-backup-nas.ps1"
    assert copy_original("Caddyfile.bak-prima-ingresso-archivio") == "Caddyfile"
    assert copy_original("a.py.orig") == "a.py"
    assert copy_original("backup-documenti-nas.ps1") is None
    assert copy_original("notes.bakery.md") is None
    assert classify("tools/x.ps1.bak-20260718") is NodeType.PROGRAM
    assert classify("tools/maestro-backup-tray.pyw") is NodeType.PROGRAM
    assert classify("tools/maestro-backup-tray.pyw.bak-1") is NodeType.PROGRAM
    assert is_copy_or_log("tools/backup.log") and is_copy_or_log("tools/app.log.3")
    assert not is_copy_or_log("tools/logger.py") and not is_copy_or_log("docs/blog.md")


def test_focus_ranks_copies_and_logs_after_the_real_files_and_their_neighbours():
    g = Graph("t")
    real = ["tools/backup-nas.ps1", "tools/backup-tray.pyw"]
    copies = [f"tools/backup-nas.ps1.bak-2026071{i}" for i in range(8)] + ["tools/backup_nas.log"]
    helper = "tools/percorsi.ps1"                   # no task word: reached only through the graph
    for p in real + copies + [helper]:
        g.add_node(Node(id=p, type=classify(p), label=p.rsplit("/", 1)[-1], path=p))
    g.add_edge(Edge(real[0], helper, EdgeType.IMPORTS))
    out = query.focus(g, "backup nas tray", budget_tokens=10_000)
    ids = [n["id"] for n in out["nodes"]]
    assert set(ids[:2]) == set(real)                 # the real files first
    assert ids[2] == helper                          # then what they use
    assert set(ids[3:]) == set(copies)               # copies and logs last, still there
    assert set(out["seeds"][:2]) == set(real)


def test_a_store_built_by_an_older_classifier_refreshes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_REFRESH_TTL", "0")
    (tmp_path / "x.pyw").write_text("print(1)\n", encoding="utf-8")
    g = freshness.load_or_refresh(tmp_path)
    assert g.nodes["x.pyw"].type is NodeType.PROGRAM
    assert not freshness.is_stale(tmp_path)
    import second_brain.classify as cl
    monkeypatch.setattr(cl, "VERSION", "vecchio")
    assert freshness.is_stale(tmp_path)              # the classifier is part of the signature
