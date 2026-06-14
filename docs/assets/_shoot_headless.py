#!/usr/bin/env python3
"""Headless, reproducible capture of the Second Brain 3D viewer for the README.

Why this exists:
- The WebGL render loop pauses when the browser window is not in the foreground, so
  ordinary OS screen-grabs of the live viewer come out with an empty (black) graph.
- We also must publish an ANONYMOUS image: no real project/file names anywhere
  (left panel, hover labels, or the detail panel on the right).

What it does:
1. Reads the freshly generated suite viewer (.secondbrain/view.html) with its inlined data.
2. Anonymizes the graph DATA itself (areas, file labels/paths, descriptions, broken-ref
   strings) deterministically, keeping each file's extension so colors/realism are preserved.
   Because the data is anonymized, hover labels AND any detail panel are anonymous by
   construction.
3. Injects a tiny bootstrap: default group-by = type, opens a synthetic (already-anonymous)
   detail panel to showcase drill-down, and re-fits the camera.
4. Renders it with headless Chrome + SwiftShader (software WebGL -> never black, no focus
   needed) into docs/assets/ui-suite.png.

Usage (from the repo root, on Windows):
    py docs/assets/_shoot_headless.py

This is an internal helper (untracked, like _make_charts.py / _shoot.js).
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import sys
from pathlib import Path

DOCS = Path(r"C:\Users\robys\Documents")
SBDIR = DOCS / ".secondbrain"
VIEW = SBDIR / "view.html"
LIB = SBDIR / "3d-force-graph.min.js"
OUT = Path(__file__).resolve().parent / "ui-suite.png"
WIN_W, WIN_H = 1680, 945

_BOOTSTRAP = """
<script>
// Bootstrap for capture: type grouping + a wide, panel-free canvas. The graph canvas holds
// no text (labels show only on hover), so the captured image is anonymous by construction.
window.addEventListener('load', function () {
  setTimeout(function () {
    try {
      var sel = document.getElementById('groupby');
      sel.value = 'type';
      sel.dispatchEvent(new Event('change'));
    } catch (e) {}
    try { document.getElementById('side').classList.add('collapsed'); } catch (e) {}
    try { document.getElementById('detail').classList.remove('open'); } catch (e) {}
    if (window.G) {
      try { window.G.width(window.innerWidth); window.G.height(window.innerHeight); } catch (e) {}
      try { window.G.zoomToFit(600, 60); } catch (e) {}
    }
  }, 300);
});
</script>
"""


def _anonymize(data: dict) -> dict:
    area_map: dict[str, str] = {}

    def area_alias(name: str) -> str:
        if name not in area_map:
            area_map[name] = f"area-{len(area_map) + 1}"
        return area_map[name]

    ctr: collections.Counter[str] = collections.Counter()
    id_map: dict[str, str] = {}
    new_nodes = []
    for n in data["nodes"]:
        t = n["type"]
        path = n.get("path")
        if t == "area":
            old = n.get("label") or n["id"].split(":", 1)[-1]
            alias = area_alias(old)
            new_id = f"area:{alias}"
            id_map[n["id"]] = new_id
            m = dict(n)
            m.update(id=new_id, label=alias, path=None, description="")
            new_nodes.append(m)
        else:
            ctr[t] += 1
            base = n.get("path", "") or ""
            leaf = base.rsplit("/", 1)[-1]
            ext = "." + leaf.rsplit(".", 1)[-1] if "." in leaf else ""
            top = base.split("/")[0] if base and "/" in base else "(root)"
            ar = area_alias(top) if top not in ("(root)", "") else "root"
            label = f"{t}-{ctr[t]}{ext}"
            new_path = f"{ar}/{label}" if path else None
            new_id = new_path if new_path else f"{t}:{ctr[t]}"
            id_map[n["id"]] = new_id
            meta = dict(n.get("meta", {}))
            if "broken_refs" in meta:
                meta["broken_refs"] = [f"missing-{i + 1}" for i in range(len(meta["broken_refs"]))]
            m = dict(n)
            m.update(id=new_id, label=label, path=new_path, description="", meta=meta)
            new_nodes.append(m)

    new_edges = []
    for e in data.get("links", data.get("edges", [])):
        s = id_map.get(e["source"])
        t = id_map.get(e["target"])
        if s and t:
            ed = dict(e)
            ed.update(source=s, target=t)
            new_edges.append(ed)

    data["nodes"] = new_nodes
    data["links"] = new_edges  # the viewer payload uses "links" (not "edges")
    data["project"] = "example suite"
    return data


def _find_chrome() -> str | None:
    cands = [
        os.environ.get("CHROME"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return None


def main() -> int:
    if not VIEW.is_file():
        print(f"viewer not found: {VIEW}\nrun:  py -m second_brain view \"{DOCS}\"", file=sys.stderr)
        return 2
    src = VIEW.read_text(encoding="utf-8")
    m = re.search(r'(<script type="application/json" id="sb-data">)(.*?)(</script>)', src, re.S)
    if not m:
        print("could not find inlined sb-data in the viewer", file=sys.stderr)
        return 2
    data = json.loads(m.group(2).replace("\\u003c", "<"))
    data = _anonymize(data)
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    anon = src[: m.start(2)] + payload + src[m.end(2) :]
    # Headless WebGL screenshots capture a cleared buffer unless preserveDrawingBuffer is on.
    # Patch ONLY this capture copy (not the shipped template) to make the 3D scene capturable.
    anon = anon.replace(
        "ForceGraph3D()(",
        "ForceGraph3D({rendererConfig:{preserveDrawingBuffer:true,antialias:true}})(",
        1,
    )
    anon = anon.replace("</body>", _BOOTSTRAP + "\n</body>", 1)

    # Write a persistent, served copy next to the vendored lib so its relative <script src>
    # resolves under the local http server. We capture it on a REAL GPU (via the browser
    # extension's canvas.toDataURL), which is reliable where headless SwiftShader renders black.
    out_html = SBDIR / "anon.html"
    out_html.write_text(anon, encoding="utf-8")
    if not (SBDIR / LIB.name).is_file() and LIB.is_file():
        shutil.copyfile(LIB, SBDIR / LIB.name)
    print(f"wrote {out_html}")
    print(f'serve:  python -m http.server 8099 --directory "{DOCS}"')
    print("open :  http://localhost:8099/.secondbrain/anon.html")
    print(f"nodes={len(data['nodes'])} links={len(data['links'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
