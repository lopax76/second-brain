"""Work registry: who is working where, so two agents never overwrite each other (0.10).

Second Brain never writes the user's files; here it acts as the shared notice board between
agents (Claude Code, Codex, ...) working in the same workspace:

* an agent's work on a project is registered — explicitly (``inizia``, with an intent and the
  files it plans to touch) or implicitly, the first time it asks to write there;
* before every write the agent asks :func:`posso_scrivere`:
    - ``blocco``     the file was declared or already written by ANOTHER agent's active work;
    - ``attenzione`` another agent is active on the same project and the file is linked (one
                     hop in the project graph) to what that agent touched — or the file changed
                     on disk since this agent last touched it (someone else wrote it in between);
    - ``ok``         otherwise. The file is recorded as touched by the asking agent;
* a work with no sign of life for ``SCADENZA_MIN`` minutes expires by itself; ``chiudi`` ends it.

The registry is one JSON file in the workspace store, rewritten atomically under its own lock.
Projects are independent: work on project A never sees or blocks work on project B.
The identity is the AGENT (``claude-code``, ``codex``, ...), so an agent never blocks itself.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from second_brain import lock
from second_brain.workspace import Workspace, find_workspace

SCADENZA_MIN = 30
REGISTRY_NAME = "lavori.json"


def _registry_dir(anchor: Path) -> Path:
    ws = find_workspace(anchor)
    return ws.store_root if ws is not None else anchor / ".secondbrain"


def _now() -> float:
    return time.time()


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _load(d: Path) -> dict[str, Any]:
    try:
        data = json.loads((d / REGISTRY_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("lavori"), list):
        data = {"lavori": []}
    return data


def _save(d: Path, data: dict[str, Any]) -> None:
    from second_brain.store import _atomic_write
    _atomic_write(d / REGISTRY_NAME, json.dumps(data, ensure_ascii=False, indent=1))


def _alive(w: dict[str, Any], now: float) -> bool:
    return w.get("chiuso") is None and now - float(w.get("battito", 0)) < SCADENZA_MIN * 60


def _project_key(path: Path, ws: Workspace | None) -> tuple[str, Path]:
    """(project id, project root) for a file or folder; the workspace root counts as 'superiore'."""
    if ws is not None:
        p = ws.project_of(path)
        if p is not None:
            return p.id, p.root
        return "superiore", ws.root
    # standalone: the nearest folder holding a .secondbrain store, else the folder itself
    for cand in (path, *path.parents):
        if (cand / ".secondbrain").is_dir():
            return cand.name, cand
    return path.parent.name, path.parent


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _sig(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return f"{st.st_size}:{st.st_mtime_ns}"


def _mine(data: dict[str, Any], agente: str, progetto: str, now: float) -> dict[str, Any] | None:
    for w in data["lavori"]:
        if w["agente"] == agente and w["progetto"] == progetto and _alive(w, now):
            return w
    return None


def _neighbours(project_root: Path, rels: set[str]) -> set[str]:
    """Files one hop away (imports/references, both ways) from ``rels`` in the project graph."""
    from second_brain import store
    g = store.load_graph(project_root)
    if g is None or not rels:
        return set()
    out: set[str] = set()
    for e in g.edges:
        if e.type.value not in ("imports", "references", "calls"):
            continue
        if e.source in rels:
            out.add(e.target)
        if e.target in rels:
            out.add(e.source)
    return out - rels


def inizia(path: str | os.PathLike[str], agente: str, intento: str = "",
           file: list[str] | None = None, sessione: str = "") -> dict[str, Any]:
    """Register (or refresh) ``agente``'s work on the project containing ``path``."""
    p = Path(path).resolve()
    ws = find_workspace(p)
    progetto, root = _project_key(p, ws)
    d = _registry_dir(p)
    now = _now()
    with lock.write_lock(d / "registro", blocking=True, timeout=30):
        data = _load(d)
        data["lavori"] = [w for w in data["lavori"] if _alive(w, now)]
        w = _mine(data, agente, progetto, now)
        if w is None:
            w = {"id": uuid.uuid4().hex[:10], "agente": agente, "sessione": sessione,
                 "progetto": progetto, "radice": str(root), "intento": intento,
                 "dichiarati": [], "toccati": {}, "inizio": now, "battito": now, "chiuso": None}
            data["lavori"].append(w)
        if intento:
            w["intento"] = intento
        for f in file or []:
            rel = _rel((root / f).resolve() if not Path(f).is_absolute() else Path(f).resolve(),
                       root)
            if rel not in w["dichiarati"]:
                w["dichiarati"].append(rel)
        w["battito"] = now
        _save(d, data)
    altri = [_describe(o) for o in data["lavori"]
             if o is not w and o["progetto"] == progetto and _alive(o, now)]
    conflitti = sorted(set(w["dichiarati"]) & {f for o in data["lavori"] if o is not w
                                                and o["progetto"] == progetto and _alive(o, now)
                                                for f in [*o["dichiarati"], *o["toccati"]]})
    return {"lavoro": w["id"], "progetto": progetto, "altri_al_lavoro": altri,
            "file_contesi": conflitti}


def _describe(w: dict[str, Any]) -> dict[str, Any]:
    return {"agente": w["agente"], "intento": w.get("intento", ""),
            "dal": _stamp(float(w["inizio"])), "ultimo_segnale": _stamp(float(w["battito"])),
            "file": sorted({*w["dichiarati"], *w["toccati"]})[:30]}


def posso_scrivere(path: str | os.PathLike[str], agente: str,
                   sessione: str = "") -> dict[str, Any]:
    """May ``agente`` write ``path`` now? ``esito`` = ok | attenzione | blocco, with the reason.

    On ``ok``/``attenzione`` the file is recorded as touched by ``agente`` (its work on the project
    is created if needed). A ``blocco`` records nothing.
    """
    p = Path(path).resolve()
    ws = find_workspace(p)
    progetto, root = _project_key(p, ws)
    rel = _rel(p, root)
    d = _registry_dir(p)
    now = _now()
    with lock.write_lock(d / "registro", blocking=True, timeout=30):
        data = _load(d)
        data["lavori"] = [w for w in data["lavori"] if _alive(w, now)]
        altri = [w for w in data["lavori"] if w["progetto"] == progetto and w["agente"] != agente]
        mio = _mine(data, agente, progetto, now)

        for o in altri:
            if rel in o["toccati"] or rel in o["dichiarati"]:
                return {"esito": "blocco", "progetto": progetto, "file": rel,
                        "motivo": (f"{rel} è in lavorazione da {o['agente']}"
                                   f" (intento: {o.get('intento') or 'non dichiarato'},"
                                   f" ultimo segnale {_stamp(float(o['battito']))}). Coordinatevi"
                                   " o aspetta che chiuda il lavoro."),
                        "altri_al_lavoro": [_describe(o)]}

        avvisi: list[str] = []
        if altri:
            touched = {f for o in altri for f in [*o["toccati"], *o["dichiarati"]]}
            if rel in _neighbours(root, touched):
                chi = ", ".join(sorted({o["agente"] for o in altri}))
                avvisi.append(f"{rel} è collegato a file su cui sta lavorando {chi}: "
                              "controlla che le modifiche siano compatibili")
        if mio is not None and mio["toccati"].get(rel):
            # the signature recorded AFTER this agent's last write (dopo_scrittura): if the file
            # moved since, someone else wrote it in between
            ora = _sig(p)
            if ora and ora != mio["toccati"][rel]:
                avvisi.append(f"{rel} è cambiato sul disco dopo la tua ultima modifica: "
                              "rileggilo prima di scrivere")

        if mio is None:
            mio = {"id": uuid.uuid4().hex[:10], "agente": agente, "sessione": sessione,
                   "progetto": progetto, "radice": str(root), "intento": "",
                   "dichiarati": [], "toccati": {}, "inizio": now, "battito": now,
                   "chiuso": None}
            data["lavori"].append(mio)
        # "" = touched, post-write signature not known yet (set by dopo_scrittura, if hooked)
        mio["toccati"].setdefault(rel, "")
        mio["battito"] = now
        _save(d, data)
    return {"esito": "attenzione" if avvisi else "ok", "progetto": progetto, "file": rel,
            "motivo": "; ".join(avvisi),
            "altri_al_lavoro": [_describe(o) for o in altri]}


def dopo_scrittura(path: str | os.PathLike[str], agente: str) -> None:
    """Record the file's signature AFTER the agent wrote it (so a later change by someone else
    is recognisable). Called by a post-write hook; harmless if never called."""
    p = Path(path).resolve()
    ws = find_workspace(p)
    progetto, root = _project_key(p, ws)
    d = _registry_dir(p)
    now = _now()
    with lock.write_lock(d / "registro", blocking=True, timeout=30):
        data = _load(d)
        mio = _mine(data, agente, progetto, now)
        if mio is None:
            return
        mio["toccati"][_rel(p, root)] = _sig(p) or ""
        mio["battito"] = now
        _save(d, data)


def chiudi(path: str | os.PathLike[str], agente: str) -> dict[str, Any]:
    """End ``agente``'s work on the project containing ``path``; returns what it touched."""
    p = Path(path).resolve()
    ws = find_workspace(p)
    progetto, _root = _project_key(p, ws)
    d = _registry_dir(p)
    now = _now()
    with lock.write_lock(d / "registro", blocking=True, timeout=30):
        data = _load(d)
        mio = _mine(data, agente, progetto, now)
        if mio is None:
            return {"chiuso": False, "progetto": progetto}
        mio["chiuso"] = now
        data["lavori"] = [w for w in data["lavori"] if _alive(w, now)]
        _save(d, data)
    return {"chiuso": True, "progetto": progetto, "toccati": sorted(mio["toccati"])}


def in_corso(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Every active work in the registry of the workspace containing ``path``."""
    p = Path(path).resolve()
    data = _load(_registry_dir(p))
    now = _now()
    return [{"progetto": w["progetto"], **_describe(w)} for w in data["lavori"] if _alive(w, now)]


__all__ = ["SCADENZA_MIN", "chiudi", "dopo_scrittura", "in_corso", "inizia", "posso_scrivere"]
