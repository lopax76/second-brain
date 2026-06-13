"""Render a 3D viewer HTML with the graph data inlined.

Inlining the data (instead of fetching a JSON file) means the viewer opens straight from
disk with no local server and no CORS issues — just double-click ``.secondbrain/view.html``.
The 3D rendering library is vendored next to the viewer (copied into ``.secondbrain/``), so it
works fully offline — no CDN, no network, nothing for an ad/script blocker to break.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from secondbrain.model import EDGE_COLORS, NODE_COLORS, Graph
from secondbrain.store import store_dir

_UI_DIR = Path(__file__).parent / "ui"
_TEMPLATE = _UI_DIR / "template.html"
_LIB = _UI_DIR / "3d-force-graph.min.js"
_TOKEN = "__SB_DATA__"


def render_view(graph: Graph) -> str:
    """Return a standalone HTML document for ``graph``."""
    data = {
        "project": graph.project,
        "nodes": [n.to_dict() for n in graph.nodes.values()],
        "links": [e.to_dict() for e in graph.edges],
        "nodeColors": {k.value: v for k, v in NODE_COLORS.items()},
        "edgeColors": {k.value: v for k, v in EDGE_COLORS.items()},
    }
    # The payload lives in a non-executable <script type="application/json"> block.
    # Escaping every "<" as < means no "</script>" (or "<!--") can break out of it;
    # JSON.parse decodes < back to "<". This also sidesteps U+2028/U+2029 issues,
    # since the block is parsed as text, not executed as JS.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    try:
        template = _TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"viewer template not found at {_TEMPLATE} - the package may be installed without "
            "its UI data files; reinstall second-brain"
        ) from exc
    return template.replace(_TOKEN, payload)


def write_view(root: str | os.PathLike[str], graph: Graph) -> Path:
    """Write the viewer + its vendored 3D library to ``<root>/.secondbrain/``; return the html."""
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "view.html"
    out.write_text(render_view(graph), encoding="utf-8")
    if _LIB.is_file():  # vendored library, referenced relatively by the viewer (works offline)
        shutil.copyfile(_LIB, d / _LIB.name)
    return out
