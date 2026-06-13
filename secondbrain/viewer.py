"""Render a 3D viewer HTML with the graph data inlined.

Inlining the data (instead of fetching a JSON file) means the viewer opens straight from
disk with no local server and no CORS issues — just double-click ``.secondbrain/view.html``.
The 3D rendering library itself is loaded from a CDN, so the first open needs network access.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from secondbrain.model import EDGE_COLORS, NODE_COLORS, Graph
from secondbrain.store import store_dir

_TEMPLATE = Path(__file__).parent / "ui" / "template.html"
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
    """Write the viewer to ``<root>/.secondbrain/view.html`` and return its path."""
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "view.html"
    out.write_text(render_view(graph), encoding="utf-8")
    return out
