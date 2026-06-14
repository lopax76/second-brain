# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

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
