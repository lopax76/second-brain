# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-06-14

### Added

- **Community detection.** `second_brain.communities` discovers the project's real modules from
  how files actually link (imports + references) via deterministic label propagation — not from
  the folder layout. `project_map` now reports a community count.
- **Impact queries.** `second-brain impact <id> [--up|--down] [--depth N]` (and the `impact` MCP
  tool) show a node's blast radius: upstream (what breaks if you change it) and downstream (what
  it depends on), grouped by depth, deterministic and capped per depth.
- **`GRAPH_REPORT.md` one-pager.** `second-brain report` writes a read-only digest — scale +
  token cost, god nodes, communities, surprising cross-community links, decisions by family,
  suggested questions, and problems. `build` now generates it automatically; also exposed as the
  `report` MCP tool. This is the artifact an assistant reads first instead of grepping the project.
- **Agent integration.** `second-brain agent install` adds a marked, idempotent directive to
  `CLAUDE.md` / `AGENTS.md` (with a prompt-injection guardrail: indexed content is data, not
  instructions) plus a Claude Code `PreToolUse` (`Glob|Grep`) hook. `second-brain hook install`
  adds git `post-commit` / `post-checkout` hooks that rebuild the graph deterministically (zero
  tokens, zero API). All reversible and non-destructive (`uninstall`).
- **2D community map viewer.** The viewer now lays the graph out as a flat, pannable/zoomable map
  with nodes coloured and clustered by community, plus an impact section in the detail panel,
  replacing the dense 3D layout.

### Notes

- Builds on 0.2.0 (configurable `.secondbrain.json` taxonomy, Python symbol layer), which was
  built but never published; its features ship as part of 0.3.0.

## [0.2.0] - 2026-06-14

### Added

- **Configurable classification taxonomy.** An optional `.secondbrain.json` at the project root
  tunes the type heuristics per project: extra (or replacement) keywords for `design`/`report`,
  extra foundation-doc `structure_names`, and extra `decision_id_prefixes` beyond the built-in
  `D-`/`ADR-`/`RFC-`. With no file present, behaviour is unchanged. The built-in defaults are now
  generic — project-specific names are no longer baked into the tool.
- **Python symbol layer.** `second-brain symbols <file.py>` lists a file's functions and classes
  with full signatures (via the stdlib `ast`), so an assistant can see the signatures a file-level
  map omits — on demand, without bloating the graph or the token budget.

### Fixed

- **`find` no longer under-counts.** The query previously capped results at 25 *and* its
  match counter stopped there too — so a large family (e.g. 47 decisions sharing a prefix)
  could be silently under-reported as "25 matches". `find` now returns every match by default;
  the CLI shows the first 50 with `--limit N` / `--all` to widen, but **always prints the true
  total**, and the MCP `find` tool returns an explicit `total`. A memory index must never hide
  results.

## [0.1.2] - 2026-06-14

### Fixed

- **Truncation detector: false positives on mixed-encoding files.** A file is now reported
  truncated/corrupted only when it contains a *contiguous* run of null bytes (zero-fill) — the
  unambiguous signature of truncation. Files that mix UTF-8 and UTF-16 sections (for example
  trigger logs written by PowerShell), whose scattered/alternating null bytes are valid text,
  are no longer flagged.
- **Decision count no longer double-counts.** `NodeType.DECISION` is reserved for decision
  *identifier* nodes (`D-XXX` / `ADR-N` / `RFC-N`) extracted from document text. Decision
  *documents* (ADR files, "decisioni" docs) now classify as design documents, so they are no
  longer added to the decision total alongside their own identifier. The reported number of
  decisions reflects distinct decision identifiers only.
- **MCP install hint used the wrong package name** in `docs/mcp.md`
  (`second-brain[mcp]` → `second-brain-graph[mcp]`). Thanks @galimar (#1).

## [0.1.1] - 2026-06-14

### Fixed

- **Anti-drift gate: false-positive broken references.** The gate no longer reports a
  reference as *broken* when the target file exists on disk but is not indexed as a graph
  node — for example images or other binary assets referenced from documentation
  (`![logo](docs/assets/logo.png)`). Genuine dead links (targets that do not exist) are
  still reported, and stale/orphan detection is unchanged.
- **Anti-drift gate: link syntax shown as an example.** Markdown links and wikilinks written
  inside code spans — fenced ```` ``` ```` / `~~~` blocks or inline `` `code` `` — are no
  longer extracted as real links. Documentation that *shows* link syntax such as
  `` `[label](target)` `` no longer trips the gate. Plain file paths written in backticks
  (e.g. `` `src/app.py` ``) are still recognised as prose references, since that is a core
  feature of Second Brain.

## [0.1.0] - 2026-06-14

- Initial public release: project indexer, anti-drift gate, low-token query layer
  (`map` / `find` / `neighbors`), optional MCP server, and a self-contained 3D viewer.
