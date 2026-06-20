# MCP server

Second Brain ships an optional [Model Context Protocol](https://modelcontextprotocol.io)
server so an AI assistant can **query** a project instead of re-reading it. It is read-only on
your sources and every tool returns small, budgeted data (ids, types, sizes, connections) —
**never file contents** — so a session bootstrap or a targeted question costs a few hundred to
a couple thousand tokens, not tens of thousands.

The server is an **optional extra**, keeping the core dependency-free.

## Install & run

```bash
pip install "second-brain-graph[mcp]"

# build the graph once (read-only on your sources), then run the server over stdio:
second-brain build /path/to/project
second-brain-mcp /path/to/project        # defaults to the current directory
```

The server lazily loads the stored graph (or builds it on first use), so it starts instantly.

## Performance on large repos

The server is long-running, so it keeps the loaded graph in an **in-process cache** and reuses it
across tool calls within a freshness window — `SECOND_BRAIN_REFRESH_TTL` seconds (**default 150**).
Within the window a tool call is served from memory (zero I/O); after it, the server re-checks the
content signature and reloads/rebuilds only if the project changed. On a ~130k-file project this is
the difference between several seconds and an instant per call. Set `SECOND_BRAIN_REFRESH_TTL=0` to
re-check on every call.

## Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `project_map` | – | Compact digest: areas (file counts / sizes / dominant types), node- and edge-type tallies, the most-connected files, and orphan / broken counts. The cheap thing to load when work starts. |
| `find` | `text` | Files/nodes whose name or path contains `text` (case-insensitive): `id`, `type`, `path`. |
| `neighbors` | `node_id`, `limit` (default 0) | A node and its incoming/outgoing connections (imports, references, area membership), size, description, and any broken refs. `limit` > 0 caps each direction and reports the true totals + `truncated` (a god-node won't flood the context); 0 = all. Returns `{ "error": "node not found", ... }` for an unknown id, so an assistant can tell "no edges" from "no node". |
| `subgraph` | `node_id`, `hops` (default 1) | A small subgraph (nodes + edges) within `hops` of `node_id`. |
| `impact` | `node_id`, `direction` (`up`/`down`/`both`, default `both`), `max_depth` (default 2), `budget` (default 0) | Blast radius grouped by depth: `upstream` = who depends on `node_id` (what breaks if you change it), `downstream` = what it depends on. Each node carries its incident `degree`; `budget` > 0 ranks the impacted nodes (nearest + most-connected first) and trims to ~that many tokens. |
| `impact_diff` | `direction` (`up`/`down`/`both`, default `both`), `max_depth` (default 2), `budget` (default 0) | Blast radius of the project's **uncommitted working-tree changes** (reads `git status`, read-only): `upstream` = who depends on the changed files (what might break), `downstream` = what they depend on, plus `unindexed` changed paths. The safety check to run before/after editing. |
| `why` | `source`, `target` | Shortest path between two nodes over knowledge edges (undirected) — how are they connected. Returns the path node-by-node with edge types; `connected: false` if unlinked. |
| `focus` | `task`, `budget` (default 2000), `signatures` (default false) | Task-aware retrieval: the minimal high-value subgraph for `task` within ~`budget` tokens. Anchors the task to the most relevant files (**BM25** lexical ranking — rare, specific terms win), runs personalised PageRank from them, and returns the top nodes + the knowledge edges among them — the context for a task, not the whole digest. Falls back to globally important nodes when nothing matches. With `signatures=true`, also returns the key function/class signatures of the top Python files (the API, without opening them). |
| `communities` | `key_files` (default 5), `surprising` (default 10), `limit` (default 0) | The project's real modules: clusters discovered from imports+references (not folders), each with size, cohesion, key files and dominant types, plus the top cross-module bridges. `limit` > 0 returns only the N largest (with the true total + `truncated`). The structural lens, far cheaper than the full `report`. |
| `report` | – | The full `GRAPH_REPORT.md` as Markdown: god nodes, communities, surprising cross-community links, decisions by family, suggested questions, and problems. The cheapest way to orient before grepping. |
| `health` | – | Anti-drift status: `ok` (bool), `broken` (list of `[source, target]` pairs), `stale` (`{added, removed, changed}` lists vs the last build), and `orphans` (count). |

All responses are plain JSON-able structures. None of them include file contents.

## Example: shapes you get back

`project_map` (abridged):

```json
{
  "project": "my-project",
  "files": 412, "areas": 6, "communities": 18, "links": 938, "size": 10485760,
  "node_types": { "program": 280, "structure": 40, "report": 18, "config": 30 },
  "edge_types": { "imports": 610, "references": 240, "belongs_to": 88 },
  "by_area": [ { "area": "src", "files": 280, "size": 5242880, "top_types": ["program"] } ],
  "most_connected": [ { "id": "src/app.py", "type": "program", "degree": 37 } ],
  "orphans": 12, "broken_refs": 3
}
```

`neighbors("src/app.py")` (abridged):

```json
{
  "id": "src/app.py", "type": "program", "path": "src/app.py",
  "size": 1234, "description": "", "broken_refs": [],
  "outgoing": [ { "id": "src/util.py", "type": "program", "edge": "imports" } ],
  "incoming": [ { "id": "src/cli.py", "type": "program", "edge": "imports" } ]
}
```

`health` (abridged) — note `broken` is a list and `stale` is a dict of lists, not scalar counts:

```json
{
  "ok": false,
  "broken": [ ["docs/guide.md", "notes/missing.md"] ],
  "stale": { "added": ["src/new.py"], "removed": [], "changed": ["README.md"] },
  "orphans": 12
}
```

(If no graph has been built yet, `health` returns `{"status": "no-baseline", "hint": "run 'second-brain build' first"}`.)

## Wiring it into an assistant

Point your MCP-capable client at the `second-brain-mcp` command with the project path as its
argument (stdio transport). For example, a generic client config entry:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "second-brain-mcp",
      "args": ["/path/to/project"]
    }
  }
}
```

A good first call in any session is `project_map` (cheap, orienting) or `report` (the full
one-pager); then drill in with `find` / `neighbors` / `subgraph` / `impact`, and use `health`
to confirm the graph isn't stale.
