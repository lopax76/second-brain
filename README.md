# Second Brain (SB)

**A living, always-fresh, low-token map of every project** — files, links, areas and
mechanics — that an AI assistant can query instead of re-reading everything, and that a
human can explore in a navigable **3D graph**.

> Not "another place to store stuff". It's the canonical, per-project picture that stays
> in sync with your files so you never lose track: no forgotten pieces, no "we discussed
> that three chats ago", no stale docs.

## Why

To understand a project's state, assistants today **re-read and search files every session**.
That is slow, incomplete, and **burns tokens** — repeatedly, and worse as the project grows.

Second Brain builds the project's graph once and keeps it fresh incrementally (outside the
model, at near-zero token cost). The assistant **queries** it and gets compact answers; the
human opens a **3D view** and sees the whole project at a glance.

- **Read-only** on your sources — it indexes, it never modifies your files.
- **Files are the truth**, the graph is derived (in `.secondbrain/`) and regenerable.
- **Per-project**, zero runtime dependencies, fully local, **$0** — no cloud, no API, no lock-in.
- **Anti-drift gate** — refuses to call things "fine" while something is stale, orphaned or broken.

## Install

```bash
pip install -e .          # from a clone
# or, once published:
# pip install second-brain
```

Requires Python 3.10+. Runtime dependencies: **none** (standard library only).

## Quickstart

```bash
secondbrain build  .          # index a project -> .secondbrain/graph.json
secondbrain gate   .          # anti-drift check: broken refs, stale files, orphans
secondbrain view   .          # write the 3D viewer (data inlined) -> .secondbrain/view.html
secondbrain stats  .          # quick counts by node/edge type
secondbrain map    .          # compact digest: areas, sizes, most-connected files
secondbrain find   util .     # find nodes by name or path
secondbrain neighbors secondbrain/model.py .   # a node and its connections
```

Open `.secondbrain/view.html` in a browser: the project title sits at the top, nodes are
colored by **type** (structure, program, report, design, data, memory, decision, config,
area), edges by **link type** (imports, doc-reference, belongs-to-area). Hover a node for a
description; filter by type or show only orphans. The graph data is inlined in the file (no
server, no CORS); the 3D library is fetched from a CDN, so the first open needs network access.

## Query layer (for AI assistants)

The point of Second Brain is that an assistant **queries** the graph instead of re-reading
files. `secondbrain map`, `find`, and `neighbors` return compact, budgeted answers (ids,
types, sizes, connections - never file contents), so situational awareness costs a few
hundred to a couple thousand tokens, not tens of thousands.

An optional **MCP server** exposes these same queries to MCP-aware assistants:

```bash
pip install "second-brain[mcp]"
secondbrain-mcp .      # serves map / find / neighbors / subgraph / health over stdio
```

The MCP server is an optional extra - the core stays dependency-free.

## How it works

1. **Index** — walk the project, classify each file into a typed node, and extract edges:
   Python imports (via `ast`), documentation references (markdown links, `[[wikilinks]]`, and
   **plain path mentions in prose** — the part standard tools miss), and area membership.
2. **Stay fresh** — content-hash diffing rebuilds only what changed (outside the model).
3. **Query / view** — the human gets the 3D view; an MCP query layer for assistants lands next.

## Node & edge types

| Node type | Meaning | Edge type | Meaning |
|---|---|---|---|
| `structure` | PROGETTO/README/ADR/foundation | `imports` | code A uses B |
| `program` | source code | `references` | A cites B (link/wikilink/path) |
| `report` | reports / analyses | `belongs_to` | node belongs to an area |
| `design` | designs / plans / specs | | |
| `data` | databases / datasets | | |
| `memory` | persistent memory files | | |
| `decision` | recorded decisions | | |
| `config` | configuration files | | |
| `area` | logical cluster | | |

## Status

Alpha (v0.1). Core graph + anti-drift gate + 3D viewer + a low-token query layer
(`map`/`find`/`neighbors`) and an optional MCP server. Operational nodes
(decisions/sessions) come next.

## Development

```bash
pip install -e ".[dev]"
pytest          # run the test suite
ruff check .    # lint
```

## License

[MIT](LICENSE).
