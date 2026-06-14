"""Render a 3D viewer HTML with the graph data *and* the 3D library inlined.

The viewer is a single self-contained file: the graph data and the rendering library are both
embedded, so it opens straight from disk with no local server, no CORS, and no sibling files to
lose when the HTML is moved or shared — just double-click ``.secondbrain/view.html``. Fully
offline: no CDN, no network, nothing for an ad/script blocker to break.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from second_brain.model import EDGE_COLORS, NODE_COLORS, Graph
from second_brain.store import store_dir

_UI_DIR = Path(__file__).parent / "ui"
_TEMPLATE = _UI_DIR / "template.html"
_LIB = _UI_DIR / "3d-force-graph.min.js"
_LIB_TAG = '<script src="3d-force-graph.min.js"></script>'
_TOKEN = "__SB_DATA__"


def render_view(graph: Graph) -> str:
    """Return a standalone, single-file HTML document for ``graph``."""
    data = {
        "project": graph.project,
        "nodes": [n.to_dict() for n in graph.nodes.values()],
        "links": [e.to_dict() for e in graph.edges],
        "nodeColors": {k.value: v for k, v in NODE_COLORS.items()},
        "edgeColors": {k.value: v for k, v in EDGE_COLORS.items()},
    }
    # The payload lives in a non-executable <script type="application/json"> block.
    # Escaping every "<" as < means no "</script>" (or "<!--") can break out of it;
    # JSON.parse decodes it back to "<". This also sidesteps U+2028/U+2029 issues,
    # since the block is parsed as text, not executed as JS.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    try:
        template = _TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"viewer template not found at {_TEMPLATE} - the package may be installed without "
            "its UI data files; reinstall second-brain"
        ) from exc
    try:
        lib = _LIB.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"viewer library not found at {_LIB} - the package may be installed without "
            "its UI data files; reinstall second-brain"
        ) from exc
    # Data first (its "<" are escaped, so it can't contain the library <script> tag), then
    # inline the library in place of the external reference. Neutralise any "</script" inside
    # the library (JS-equivalent) so it can't close the inline block early.
    html = template.replace(_TOKEN, payload)
    lib_inline = lib.replace("</script", "<\\/script")
    return html.replace(_LIB_TAG, f"<script>\n{lib_inline}\n</script>")


def write_view(root: str | os.PathLike[str], graph: Graph) -> Path:
    """Write the single-file viewer to ``<root>/.secondbrain/view.html``; return its path."""
    d = store_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "view.html"
    out.write_text(render_view(graph), encoding="utf-8", newline="\n")
    return out
