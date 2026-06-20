# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-06-20

### Added

- **BM25 lexical ranking for `focus`** (new zero-dependency `bm25.py`, stdlib only) — the task is
  now anchored to seed files by Okapi BM25 (IDF x saturated term-frequency over each node's
  id/path/label/type, symbol qualified name and description) instead of a flat token count. A task's
  *rare, specific* terms (`pagerank`, a decision id, a symbol name) now dominate over ubiquitous
  ones (`test`, `py`), so the personalised-PageRank restart vector anchors on the right files.
  snake_case identifiers are split into components, so `focus "auth login"` matches `auth_login.py`.
  No new dependency, deterministic, and `focus` falls back to global rank when nothing matches.
- **Transparent budgeting on the flood-prone tools** — `neighbors` and `communities` (CLI + MCP)
  take an optional `limit`: `neighbors --limit N` caps each direction and reports `outgoing_total` /
  `incoming_total` + `truncated`; `communities --limit N` returns only the N largest clusters with
  the true `count` + `shown` + `truncated`. Default (0) is unchanged — every row, fully backward
  compatible — so a god-node or a huge community list can no longer silently flood an agent's context.

### Note

These are the two on-brand, zero-dependency patterns absorbed from a study of Headroom (a context-
compression layer): better lexical relevance for retrieval, and explicit, reversible output budgeting.
Headroom itself (proxy, ML compression model, embeddings/HNSW, mutable memory) was deliberately not
adopted — it would break Second Brain's zero-dependency, read-only, deterministic core.

## [0.6.1] - 2026-06-16

### Fixed

- **README version** — the *Status & roadmap* section still read "Beta - v0.5.0" while the package
  was already 0.6.0 (a stale line missed in the 0.6.0 bump). It now reads "Beta - v0.6.1", and the
  "working today" list includes `communities` and per-file `type_overrides`.

### Packaging

- `CHANGELOG.md` is now shipped in the source distribution (via `MANIFEST.in`), so the change
  history is discoverable from the PyPI source archive, not only on GitHub.

## [0.6.0] - 2026-06-16

### Added

- **`communities`** — the project's real modules as a first-class query: a new MCP tool and a
  `second-brain communities` CLI command surface the community detection (clusters from
  imports+references, with size, cohesion, key files and dominant types) plus the top
  cross-module bridges. Previously this lived only inside the full `report`; now an assistant can
  ask for the structural lens directly, at a fraction of the tokens. The MCP server is now
  **11 tools**.
- **Per-file node-type overrides** — `.secondbrain.json` accepts a `classify.type_overrides` map
  (`{ "path/to/file": "data" }`) to pin a file's node type when the heuristic guesses wrong,
  without touching the algorithm. Opt-in and fail-safe: unknown or `area` type names are ignored,
  and with no file the classification is byte-identical.

### Changed

- **`impact --diff` clarity** — when every impacted node is itself among the changed files, the
  result now carries an explicit `note` (and the CLI prints `(none - every impacted node is
  already among your changed files)`) instead of a bare `(none)`, which read as "no impact".

### Tests

- New `tests/test_v06_features.py` (16 tests) covering the community query/tool, the `impact --diff`
  note, the type overrides, and **end-to-end execution of all 11 MCP tools** (the server's tool
  bodies were previously uncovered). Coverage 91% -> 93%; `mcp_server.py` 0% -> 85%. 257 tests total.

## [0.5.0] - 2026-06-15

### Added

- **`impact --diff`** (and the `impact_diff` MCP tool) — the blast radius of your **uncommitted
  working-tree changes**: reads `git status` (read-only), maps the changed files to nodes, and
  reports what depends on them (`upstream` — what might break) and what they depend on
  (`downstream`), unioned and de-duplicated across all changed files. The safety check to run
  before/after editing. The store dir (`.secondbrain/`) is never counted as a change.
- **`why <a> <b>`** (and the `why` MCP tool) — the shortest path between two nodes over the
  knowledge edges (undirected): "how are these two things connected?" Returns the path node-by-node
  with edge types, deterministic (a tie picks the lexicographically smallest path).

## [0.4.0] - 2026-06-15

### Added

- **Self-refreshing reads (always fresh by default).** Every query (`map` / `find` / `neighbors` /
  `impact` / `focus` / `report` and the MCP tools) checks a cheap size+mtime signature and rebuilds
  the graph only when the project actually changed — including *uncommitted* edits — so an assistant
  never answers from a stale map. First use of a project auto-builds. No scheduler, no dependencies.
  Disable with `SECOND_BRAIN_AUTO_REFRESH=0`; throttle on a huge single graph with
  `SECOND_BRAIN_REFRESH_TTL=<seconds>`. A failed store write (read-only checkout) degrades to
  serving the in-memory graph instead of crashing. The store now also keeps a `signature.json`
  for the stat-only staleness check.
- **PageRank ranking (`second_brain.rank`).** Structural importance over the knowledge graph
  (imports/references), pure-Python, deterministic, with dangling-mass handling and an optional
  personalised restart vector. The `report` "god nodes" now rank by importance instead of raw
  degree.
- **Task-aware budgeted retrieval — `second-brain focus "<task>" [path] --budget N`** (and the
  `focus` MCP tool). Anchors the task to matching files, runs personalised PageRank from them, and
  returns the minimal high-value subgraph within a token budget (seeds first) plus the knowledge
  edges among the chosen nodes — the context for a task, not the whole digest. Falls back to
  globally important nodes when nothing matches. Personalised-PageRank scores are cached
  (structurally-keyed, LRU-bounded) for fast repeated queries in a long-running MCP server.
- **Opt-in Python symbol layer — `second-brain build --symbols`.** Adds function/class nodes
  (`symbol`) and intra-file `calls` edges via `ast`. Resolution is deliberately conservative
  (`self.m()` → the enclosing class's method; bare `f()` only when unique in the file; a class
  never inherits its methods' calls; non-`self` attribute calls are not guessed) to avoid
  name-based false edges. Off by default; symbol nodes carry no path, so file counts/areas/orphans
  are unaffected.
- **GraphML export — `second-brain export [path] --format graphml [--out file]`.** Deterministic
  XML for Gephi / yEd / Cytoscape / networkx. Pure stdlib.
- **Churn in the report.** A "Most-changed files (recent churn)" section derived from git
  `touches` edges — historical hot spots, complementary to PageRank's structural importance
  (shown only when the project has git history).

### Changed

- **Honest docs on rebuild cost.** The README (EN + IT) and `docs/graph-format.md` previously
  said the build "rebuilds only what changed" / "drives incremental rebuilds". It does not: a
  build is a full re-walk (fast). The content-hash manifest powers the anti-drift **gate**'s
  staleness check (which files changed since the last build), not a partial rebuild. Wording
  corrected to match the code. (A truly incremental build remains a possible future feature.)

### Fixed

- **Final pre-0.4.0 gate (30-agent audit).** The auto-refresh signature is now captured *before*
  the build walk, so an edit landing mid-build degrades to a safe rebuild (false-stale) instead of
  a permanent false-fresh; `SECOND_BRAIN_REFRESH_TTL=inf`/`nan` no longer freezes the staleness
  check; the report's god-node filter excludes session/decision nodes to match its docstring; the
  CI matrix now also tests Python 3.14 (claimed in the classifiers).
- **Hardening (roadmap items).** `Graph` keeps a lazily-built adjacency index, so
  `neighbors()` / `degree()` are O(degree) per call instead of re-scanning every edge (behavior
  identical, including per-edge-type and self-loop counting). `agent install` / `hook install`
  match their managed block by regex — collapsing accidental duplicates and staying robust to a
  stray marker pasted by the user (re-install is idempotent). The viewer payload and
  `project_map` use an explicit `sorted()` for guaranteed determinism. `__all__` added to the
  public modules (`model` / `store` / `query` / `gate` / `freshness` / `viewer`).
- **Deep-audit hardening (30-agent review).** `iter_files` skips Windows junctions/reparse points
  (no index loop/explosion) and `_is_external` treats absolute POSIX paths (`/etc/...`) as external
  (no false broken refs); the wikilink regex is ReDoS-hardened like the markdown one (9s → ~0 on a
  pathological `[[` run); `js_imports` ignores comments and also matches dynamic `import()` and
  backtick specifiers; the symbol call-graph no longer attributes decorator / default-argument /
  annotation calls to the function; `classify` recognises plural folder names (`designs/`,
  `reports/`, `specs/`); `assess` no longer flags `py.typed` as empty; `store.load_graph` degrades
  to `None` on non-dict JSON (e.g. a top-level array); `Node`/`Edge` copy their `meta` (no caller
  aliasing); `.py` files are read once in `--symbols` mode; `rank` type hints tightened (no
  `type: ignore`); CONTRIBUTING / PR-template ruff command corrected (`second_brain`).
- **Cross-check hardening (15-agent review).** `focus`'s cache fingerprint now includes the node
  set (not just edges), so two graphs differing only by an isolated-node turnover can't collide;
  the markdown-link regex excludes `]` and is length-capped (no ReDoS on pathological `](` runs);
  the build mode (`--symbols`) is persisted in `mode.json` so a self-refresh keeps indexing symbols
  even when the stored graph had none yet; a self-refresh rebuild that fails for *any* reason (not
  just I/O) degrades to the loaded graph instead of crashing. `focus` is now listed in
  `docs/mcp.md`, and the `symbol` / `defines` / `calls` types in `docs/graph-format.md`.
- **`symbols` CLI consistency.** `second-brain symbols <file> [path]` now takes an optional
  project root (default `.`), like `find` / `neighbors` / `impact`, and resolves the file under
  it. Previously a second argument raised `unrecognized arguments`. Missing files still fail
  loudly (exit 2 + `not a file` on stderr), never silently. Verified argparse-compatible on
  Python 3.12.
- **Conservative broken-reference resolution.** A markdown/wikilink is reported as *broken* only
  when its target looks like a project file (path separator or a letter-initial extension). This
  removes false positives from code fragments in HTML docs (minified JS `](A)` / `](this.easingTime)`)
  and from version strings (`[v1.2](v1.2)`), while still catching genuine broken file links.
  (On this repo: 9 false "broken refs" → 0.)

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
- **Interactive graph viewer (vis-network, adapted from Graphify).** Offline single-file viewer
  built on **vis-network** (Apache-2.0 OR MIT, vendored): force-directed layout with community
  colouring, search, a click-to-inspect **Node Info** panel with clickable neighbour navigation,
  and a per-community **show/hide legend** with "Select All". The viewer is **adapted from
  [Graphify](https://github.com/safishamsi/graphify)** (MIT, © Safi Shamsi) — with thanks; see
  `THIRD_PARTY_NOTICES.md`. Replaces the earlier 3d-force-graph layout.

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
