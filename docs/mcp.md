# MCP server

Second Brain ships an optional [Model Context Protocol](https://modelcontextprotocol.io)
server so an AI assistant can **query** a project instead of re-reading it. It is read-only on
your sources and every tool returns small, budgeted data (ids, types, sizes, connections) —
**never file contents** — so a session bootstrap or a targeted question costs a few hundred to
a couple thousand tokens, not tens of thousands.

The server is an **optional extra**, keeping the core dependency-free.

## Install & run

```bash
pip install "second-brain[mcp]"

# build the graph once (read-only on your sources), then run the server over stdio:
secondbrain build /path/to/project
secondbrain-mcp /path/to/project        # defaults to the current directory
```

The server lazily loads the stored graph (or builds it on first use), so it starts instantly.

## Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `project_map` | – | Compact digest: areas (file counts / sizes / dominant types), node- and edge-type tallies, the most-connected files, and orphan / broken counts. The cheap thing to load when work starts. |
| `find` | `text` | Files/nodes whose name or path contains `text` (case-insensitive): `id`, `type`, `path`. |
| `neighbors` | `node_id` | A node and its incoming/outgoing connections (imports, references, area membership), size, description, and any broken refs. Returns `{ "error": "node not found", ... }` for an unknown id, so an assistant can tell "no edges" from "no node". |
| `subgraph` | `node_id`, `hops` (default 1) | A small subgraph (nodes + edges) within `hops` of `node_id`. |
| `health` | – | Anti-drift status: `ok` (bool), `broken` (list of `[source, target]` pairs), `stale` (`{added, removed, changed}` lists vs the last build), and `orphans` (count). |

All responses are plain JSON-able structures. None of them include file contents.

## Example: shapes you get back

`project_map` (abridged):

```json
{
  "project": "my-project",
  "files": 412, "areas": 6, "links": 938, "size": 10485760,
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

(If no graph has been built yet, `health` returns `{"status": "no-baseline", "hint": "run 'secondbrain build' first"}`.)

## Wiring it into an assistant

Point your MCP-capable client at the `secondbrain-mcp` command with the project path as its
argument (stdio transport). For example, a generic client config entry:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "secondbrain-mcp",
      "args": ["/path/to/project"]
    }
  }
}
```

A good first call in any session is `project_map` (cheap, orienting); then drill in with
`find` / `neighbors` / `subgraph`, and use `health` to confirm the graph isn't stale.
