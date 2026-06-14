# Graph format & data model

This document describes what Second Brain writes to disk, the shape of the graph, the node /
edge taxonomy, and the rules used to classify files and extract references. It is the
reference an integrator (or an AI assistant) needs to consume the graph directly.

## What's on disk: `.secondbrain/`

`second-brain build` writes a single, regenerable store next to the project (never touching
your sources). Writes are atomic (temp file + `os.replace`), so a crash can't leave a
half-written graph.

| File | Produced by | Purpose |
|------|-------------|---------|
| `graph.json` | `build` | The graph itself (nodes + edges). The thing you consume. |
| `manifest.json` | `build` | `{ "<relative/path>": "<content-hash>" }`, sorted. Drives incremental rebuilds and the anti-drift gate's *stale* check. |
| `view.html` | `view` | A self-contained **2D community-map** viewer with the graph data *and* the rendering library both inlined — a single file that works fully offline (see note below). |
| `GRAPH_REPORT.md` | `build`, `report` | A read-only Markdown one-pager: scale + token cost, god nodes, communities, surprising cross-community links, decisions by family, suggested questions, and problems. The artifact an assistant reads first. |

## `graph.json`

Deterministically ordered (nodes by `id`, edges by `(source, target, type)`) so diffs and
content hashes are reproducible.

```json
{
  "project": "my-project",
  "nodes": [
    {
      "id": "src/app.py",
      "type": "program",
      "label": "app.py",
      "description": "",
      "path": "src/app.py",
      "meta": { "size": 1234 }
    },
    {
      "id": "area:src",
      "type": "area",
      "label": "src",
      "description": "",
      "path": null,
      "meta": {}
    }
  ],
  "edges": [
    { "source": "src/app.py", "target": "src/util.py", "type": "imports", "meta": {} },
    { "source": "src/app.py", "target": "area:src", "type": "belongs_to", "meta": {} }
  ]
}
```

### Node

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Stable, unique. POSIX relative path for files; `area:<name>` for areas. |
| `type` | string | One of the node types below. |
| `label` | string | Short human name (usually the file's basename). |
| `description` | string | Optional short explanation shown in the viewer. |
| `path` | string \| null | POSIX relative path for file-backed nodes; `null` for areas. |
| `meta` | object | Free-form. Common keys: `size` (bytes), `broken_refs` (list of unresolved targets), `hidden` (count of summarized files, on area nodes in backbone mode). |

### Edge

A directed `source → target` between node ids, de-duplicated by `(source, target, type)`.

| Field | Type |
|-------|------|
| `source` | string (node id) |
| `target` | string (node id) |
| `type` | string (one of the edge types below) |
| `meta` | object |

> **Colors are not stored.** They are derived from `type` (single source of truth in
> `second_brain/model.py`), keeping the store small and drift-free.

> **Viewer payload differs slightly.** Inside `view.html` the data is inlined with edges
> renamed to **`links`** and two extra maps, `nodeColors` / `edgeColors` (so the page is
> self-contained). On disk, `graph.json` uses **`edges`** and no colors.

## Node types

| Type | Color | Meaning |
|------|-------|---------|
| `structure` | `#1E3A8A` | Foundation docs: README, PROGETTO, ADRs, index. |
| `program` | `#16A34A` | Source code. |
| `report` | `#D97706` | Reports / analyses / audits / dated notes. |
| `design` | `#7C3AED` | Designs, plans, specs, roadmaps. |
| `data` | `#0D9488` | Databases / datasets. |
| `memory` | `#DB2777` | Persistent memory files. |
| `decision` | `#DC2626` | A recorded decision (added by the operational layer). |
| `config` | `#EA580C` | Configuration files. |
| `area` | `#6B7280` | A logical cluster (a top-level folder). |
| `session` | `#92400E` | A work session / git commit (operational layer). |

## Edge types

| Type | Color | Meaning |
|------|-------|---------|
| `imports` | `#16A34A` | Code A imports / uses B. |
| `references` | `#D97706` | A cites B (markdown link, wikilink, or path-in-prose). |
| `belongs_to` | `#6B7280` | A file belongs to an area. |
| `mentions` | `#DC2626` | A document mentions a decision. |
| `touches` | `#92400E` | A session/commit touched a file. |

## How files are classified

Classification is a documented, conservative heuristic (`second_brain/classify.py`); order
matters — more specific signals win:

1. **memory** — path contains a `memory` segment, or name starts with `memory.`
2. **data / program / config** by extension (strong signals), plus well-known config names
   (`.gitignore`, `Dockerfile`, `Makefile`, `Caddyfile`, …).
3. **structure** by name — `README`, `PROGETTO`, `INDEX`, `CHANGELOG`, `LICENSE`, …
4. **document sub-typing** (for doc-like files): `decision` → `design` → `report`
   (keyword/date), else fall back to `structure`.
5. **anything else** (unknown extension) → `config`.

Code import edges are real parses: Python via the `ast` module; JS/TS via a lightweight
import scan. Other languages contribute via documentation links rather than code imports.

## How references are extracted (and why prose mentions don't add noise)

Three kinds are recognized (`second_brain/references.py`):

- **Markdown links** `[label](target)`
- **Wikilinks** `[[Name]]` / `[[Name|alias]]`
- **Plain path mentions in prose** — e.g. `src/app.py` written inside a sentence. This is the
  part standard tools miss, and a core reason Second Brain exists for documentation.

Plain prose mentions are inherently noisy (a path in an example or a comment is not always a
real reference). Second Brain handles this asymmetrically:

- **links / wikilinks** are intentional, so an unresolved one is reported as **broken**.
- **a plain prose mention is used only if it resolves** to an actual project file; if it
  doesn't, it is silently dropped as noise — it never creates a broken reference.

This keeps recall high (you catch real path mentions) without flooding the gate with false
positives.

## Anti-drift gate

`second-brain gate` refuses to call the graph "fine" while it is out of date, by three signals:

- **broken** (error) — a link/wikilink points inside the project but the target is missing.
- **stale** (error) — files were added / removed / changed since the last build (the manifest
  no longer matches the tree) → rebuild needed.
- **orphans** (info) — file nodes with no import/reference edge. Often legitimate (a truly
  standalone file), so orphans are reported but never fail the gate.

## Known limitations

Classification and reference extraction are deliberately simple, fast heuristics. Known
trade-offs you should expect (and can work around by drilling into a subfolder or relying on
the explicit links/imports):

- **Directory names influence type.** The decision/design/report keyword checks look at the
  whole relative path, so a file under `design/`, `adr/`, or `reports/` is typed accordingly
  even if its own name is neutral. This is intentional (folder intent is a strong signal) but
  can over-type files in such folders.
- **`.json` is treated as config.** Domain data or fixtures stored as `.json` are counted as
  `config`, not `data`, so the `data` tally understates JSON datasets.
- **Keyword/date heuristics are language- and pattern-specific.** Both English and Italian
  keywords are recognized (e.g. `design`/`disegno`, `plan`/`piano`), which can occasionally
  match an unrelated word; a year-month like `2026-06` in a filename marks it as a `report`.
- **Ambiguous references are dropped silently.** If a link/wikilink target matches two or more
  files by basename/stem, it is not resolved and not reported as broken (to avoid guessing).
  Use a path-qualified target to disambiguate.
- **Deep import parsing is Python + JS/TS only.** Other languages contribute through
  documentation links, not code-import edges. A `src/`-layout package whose modules are
  imported as top-level names may not resolve every internal import.
