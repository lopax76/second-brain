# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [0.9.5] - 2026-07-26

The four defects 0.9.4 listed as *known and not fixed*. Three are closed; the fourth is reduced
and, where an irreducible residue remains, now **declared** instead of implied.

### Fixed

- **Two overlapping builds can no longer leave an incoherent store.** Each file was written
  atomically, but nothing bound the *set*: the survivors could be one build's `graph.json` beside
  another's `manifest.json` and `signature.json` — correct in everything `gate` and `is_stale`
  consult, stale in the thing actually served. Nothing looked wrong, so no rebuild ever fixed it.
  `save` now ends by writing `stamp.json`, the digests of those three files together; `load_graph`
  verifies it and refuses a set that never came from a single build, which costs a rebuild instead
  of going quietly wrong. A store written before stamps existed has none and is still accepted —
  absence of a stamp is not evidence of incoherence.
- **Editing `.secondbrain.json` now counts as the project changing.** SB's own config files are
  excluded from the walk, so they were absent from the signature — yet the graph depends on them:
  `classify` decides node types and `respect_gitignore` decides which files exist at all. Changing
  the `classify` block left a stale graph reporting itself fresh, with `gate` green, for every
  subsequent query. Both config files are now digested into the signature under `:config:` keys.
- **A momentarily unreadable file no longer loses its edges for good.** A file held open
  exclusively (an editor, Excel, an antivirus, a log writer) was *omitted* from the signature — and
  so was omitted from a fresh one too, so the two agreed and nothing ever retried it. It is now
  recorded as `!unreadable`, which matches no real value: the file is re-read as soon as it can be,
  and while it stays locked there is no rebuild thrashing either.

### Changed

- **Above the content-hash cap the stamp uses `st_mtime_ns`, not whole seconds.** Two different
  contents of the same length written inside one second used to produce the *same* manifest value,
  so `gate` — which recomputes exactly that value — reported clean over a changed file. Free to fix,
  and it removes that collision entirely.
- **`gate` now names the files it could only check by size+mtime.** Above the cap no bytes are read,
  by design, so "clean" is a weaker statement for those files than for every other one. A
  replacement that preserves size *and* exact mtime (`cp -p`, `tar -x`, a restore, a coarse-grained
  filesystem) remains invisible to any stat-based check — that residue is real and is the reason
  this is reported rather than claimed fixed.
- `tests/test_cli.py` no longer copies a `.secondbrain` left in the fixture by an earlier run, which
  had been handing the "first" build a warm cache and making those tests order-dependent.

## [0.9.4] - 2026-07-26

A cross-check aimed squarely at test quality — sabotage the code, see whether anything fails —
found that several of the properties 0.9.2 and 0.9.3 claim to protect were guarded by nothing.
No behaviour changes here beyond one dead function: this release is the tests, plus the docs that
had drifted away from the code.

### Added

- **Eleven independent sabotages, each now caught by a named test.** Verified by re-applying every
  one of them to a copy of the repo and confirming the suite fails: the mid-build double read, the
  freshness signature captured too late, a forgotten statement field in the import scanner, the
  coarse stamp used as a cache key, `_atomic_write` without its temp file, GraphML losing its sort,
  `build` exiting 0 without persisting, `--full` silently ignored, cache type-validation removed,
  `RecursionError` uncaught, and dangling symlinks dropped from the graph.
- **A differential test for the import scanner** (`tests/test_pycode.py`): `python_imports` is
  compared against a reference `ast.walk` implementation on every construct that nests statements
  — `match`/`case` (nested, and with guards), `except*`, `async with`/`async for`, loop `else`,
  class-in-function. Removing a field from `_STMT_FIELDS` now fails the suite; before, dropping
  `cases` lost every import inside a `match` and 325 tests stayed green.
- Tests for the CLI surface added in 0.9.2/0.9.3: the `reused:` line, `--full`, and the non-zero
  exit plus stderr warning when the store cannot be written.
- A test that the store survives a failed write with the previous version intact and no `.tmp-*`
  left behind — the atomicity the module docstring has always promised.

### Fixed

- **Two tests were vacuous.** The pair covering the cache above the content-hash cap wrote
  `[link](alpha.py)` then `[link](zeta.py)` while claiming "same byte length": those differ by one
  byte, so the size in the coarse stamp invalidated the cache on its own and the collision the
  tests existed to provoke never happened. Targets are now isometric *and* the test asserts it.
- `test_graphml_deterministic` was `to_graphml(g) == to_graphml(g)` — true of any pure function,
  blind to the insertion-order dependency it was meant to catch. It now compares two equivalent
  graphs built in opposite order.
- `test_cache_from_a_future_version_is_ignored` injected the integer `CACHE_VERSION + 1` while
  `cache_id()` returns a string, so it tested type rejection rather than a future identity.
- **Documentation that had stopped being true**: both READMEs still said `v0.9.0` and listed
  incremental indexing under "next steps" — the headline feature of the two releases before this
  one; `build --full` was documented nowhere outside argparse's help; `docs/graph-format.md` and
  the module tables never mentioned `extract.json`; three places described the cache key as a
  content digest without the above-the-cap exception; `store.py` described two of the five files
  it writes; and the `[0.9.3]` entry was dated a day before the commit containing it.
- Removed `freshness._stat_sig`, orphaned when 0.9.3 merged the two passes, and a comment pointing
  at `indexer._TEXT_EXTS`, a name deleted in 0.9.2.

## [0.9.3] - 2026-07-26

Everything here comes from an adversarial cross-check of 0.9.2. Its central promise — an
incremental result identical to a full rebuild — did not hold, and the reason is worth recording:
the digest and the findings were taken from **two separate reads at two different instants**.

### Fixed

- **A file edited during a build could poison the cache permanently.** The manifest pass digested
  a file at one moment and the extraction pass parsed it at another, so an entry could be stored
  as "digest of version X, findings of version Y". When the file then settled on X — the common
  case, the digest pass runs first — every later build recomputed X, matched the cache, and served
  Y's findings again, for good. `gate` could not see it: it compares digests with digests, and
  those agreed. **The bytes are now read once and both the digest and the findings come from those
  bytes**, so a mislabelled entry is not unlikely, it is unrepresentable. This also removes the
  CRLF/size-cap mismatch (a digest over newline-normalized bytes was compared against a cap
  checked on the raw size) and the re-read of every extractable file above 1 MB on every build.
- **The cache identity is now bound to `second_brain.__version__`**, not to a hand-maintained
  constant. Keying an entry on file content says what was read, never *who read it*: a release
  that changes what an extractor finds — 0.9.2 rewrote `python_imports` — would otherwise serve
  the old findings forever for every already-cached file if whoever cut it forgot to bump.
- **A stored entry is type-checked, not just shape-checked.** A numeric reference target or a
  nested list where a string belongs used to survive parsing and crash inside reference
  resolution, far from any guard.
- **`RecursionError` no longer escapes the store guard.** It is a `RuntimeError`, not a
  `ValueError`, so deeply nested JSON in `extract.json` crashed `build` on every run — only
  `--full` survived, because it never loads the cache.
- **A file deleted between the walk and the build is no longer a permanent phantom node.** It used
  to keep its edges while being absent from both signature and manifest, so no later walk could
  notice it and `gate` stayed green. An entry that *exists but cannot be stat'ed* — a dangling
  symlink, which is what a git clone of a symlinked `AGENTS.md` leaves on Windows — is
  deliberately kept, because documents link to it and dropping it would silently turn those links
  into broken references.
- **`build` no longer crashes when the store cannot be written** (read-only checkout, locked
  directory, full disk). It warns, still prints the graph, and exits non-zero so a hook or CI can
  tell that nothing was persisted.

### Measured

22.233 files: cold **16,1s**, rebuild after one edit **5,1s**. 5.243 files / 120 agents: cold
**1,90s**, rebuild **1,71s**. Incremental verified byte-identical to a from-scratch build at both
scales. 325 tests, ruff clean.

### Changed

- Above the content-hash cap the cache key is the precise `size:mtime_ns` signature rather than a
  re-read digest. That removes a full re-read of every large extractable file on every build (48 MB
  read on a no-op build, in one measurement) and the same-second collision the coarse stamp allows.
  The trade-off, stated plainly: for those files the key is *stat* evidence, not content evidence —
  the same evidence `is_stale` already trusts to decide whether to rebuild at all, and no weaker
  than the known-and-open item about `gate` above the cap.

### Known and NOT fixed (pre-existing, found by the same cross-check) — **all addressed in 0.9.5**

- **Two overlapping builds can leave `graph.json` from one and `manifest.json`/`signature.json`
  from the other.** `store.save` writes each file atomically but takes no lock across them, so the
  result is a permanent false-fresh with a green `gate`. Needs either a lock or a consistency
  stamp over the whole store; it is not specific to incremental indexing.
- **For files above the content-hash cap, `gate` is not a content check** — it recomputes the same
  coarse `size + whole-second mtime` stamp the freshness signature uses. A replacement preserving
  size and mtime (`cp -p`, `tar -x`, a backup restore, a coarse-grained filesystem) is invisible
  to both.
- **`.secondbrain.json` is in neither the signature nor the manifest**, so changing the `classify`
  block leaves a stale graph that reports fresh.
- **A file locked for an instant during a build loses its edges** for that build and, above the
  cap, without `gate` noticing.

## [0.9.2] - 2026-07-25

Scaling release: make a rebuild proportional to what *changed*, not to how big the project is.
Measured on a real 22.233-file tree (a multi-product workspace with a vendored monorepo) and on
a 5.243-file / 120-agent projection of it.

### Added

- **Incremental indexing** — a rebuild now re-reads only the files whose content actually moved.
  Indexing is split in two: **extraction** (open one file, pull out its imports / reference
  targets / symbols) is per-file and cached in `.secondbrain/extract.json`, keyed by the same
  content hash the manifest already computes; **resolution** (turning those raw targets into
  edges against the whole file set) is cheap and is redone **globally on every build**.
  That split is what makes the result *byte-identical* to a full rebuild rather than merely
  close to it — no edge is ever carried over, only raw per-file findings — so the usual failure
  mode of incremental graph updates (a stale cross-file edge quietly surviving) cannot occur.
  Adding, deleting or renaming a file still updates the edges of documents that did not change.
  Verified by tests that assert equality against a from-scratch build, including on the real
  22k-file tree. New `extract.py`; `build --full` forces a complete re-read. Zero new dependency.
  - 22.233 files: cold **18,1s**, rebuild after one edit **4,6s** (**3,9×**).
  - 5.243 files / 120 agents: cold **2,57s**, rebuild after one edit **1,82s**.

  The cache is keyed on a **content digest**, never on the manifest's `size + whole-second mtime`
  fallback for files above the content-hash cap: two different contents can share that stamp
  (same length, same second), and keying on it served a stale parse that `gate` could not see —
  it recomputes the very same stamp. Large extractable files therefore get a real digest.
- **`second-brain build --full`** — ignore the cached extraction and re-read everything.
- `index_cached()` / `BuildResult` — the build entry point that returns the extraction cache and
  the freshness signature alongside the graph and manifest. `index()` is unchanged for callers
  that do not need them.

### Changed

- **Import scanning no longer walks the whole AST.** An import is a *statement*, so it can only
  appear inside a statement list — never inside an expression. Visiting only statement fields
  (in each node's own `_fields` order, so the breadth-first order is preserved) skips the bulk
  of a Python AST. Measured on ~2.000 real Python files, import collection costs **3,3s** with
  `ast.walk` against **2,1s** here — of which 2,0s is `ast.parse` itself, unavoidable either way;
  a full index of a 5.200-file Python-only tree drops from **11,1s to 6,9s**. (An earlier draft of
  this entry claimed 26,9s of a 34,4s index; that figure was not reproducible and is withdrawn.)
  Verified to return results identical to `ast.walk` on ~2.000 real Python files, and — since
  0.9.3 — by a differential test in the suite covering every statement-nesting construct. A source
  without the substring `import` is now skipped without parsing at all (exact, not heuristic).
- **The project tree is walked once per build, not twice.** The freshness signature used to come
  from a separate `fast_signature()` pass before indexing; it is now produced by the build's own
  walk. About a second of duplicated `stat` on a 5.000-file tree. The ordering guarantee is
  unchanged: the signature is still captured before any file's contents are read, so a file that
  appears mid-build reads as stale next time (safe) rather than as fresh.
- **The manifest is recomputed from the files on every build, never carried over.** An earlier
  cut of this release reused the stored hash when a file's size+mtime had not moved. It was
  faster and it was wrong: the store could then hold a hash that did not match the file, and the
  state was **self-perpetuating** — the stale hash validated the stale cache entry, which
  regenerated the stale hash, so `gate` reported drift while every rebuild faithfully reproduced
  it and only `--full` broke the loop. The manifest is what `gate` compares against, so it has to
  be evidence rather than memory, and a rebuild has to be able to *heal* a drifted store. Paying
  the re-hash is what buys that: it is the difference between 2,8s and 4,6s on the 22k tree.

### Fixed

- **A UTF-8 BOM no longer silently disables SB's own config files.** Notepad and PowerShell 5.1's
  `Set-Content -Encoding utf8` both write a BOM. `.secondbrain.json` then failed to parse and
  fell back to defaults (so `respect_gitignore` stayed off), and the BOM glued itself to the
  first rule of `.gitignore`/`.secondbrainignore`, silently killing that rule. All three readers
  now use `utf-8-sig` — identical to `utf-8` when no BOM is present. (Backlogged as 0.9.1.)

## [0.9.0] - 2026-06-20

### Added

- **Recency-weighted recall — the base-level of memory** (`focus --recency W`, MCP
  `focus(recency=…)`, off by default). On top of the *associative* recall that personalised
  PageRank already provides (the spreading-activation half of human declarative memory), `focus`
  can now blend in the **base-level** half — recency and frequency — derived from git history that
  is **already in the graph** (`session` nodes carry the commit date, `touches` edges the files
  they changed). A recently or frequently changed file can outrank a structurally important but
  dormant one. The signal is anchored to the **most recent commit in the graph, never the wall
  clock**, so output stays deterministic; it adds **no new dependency and no extra indexing**, and
  is a no-op without git history. `--half-life DAYS` (default 30) tunes the decay. New
  zero-dependency `recency.py`; plain `focus` (`--recency 0`) is byte-identical.
- **Opt-in `.gitignore` support** — set `"respect_gitignore": true` (top level of
  `.secondbrain.json`) and the indexer also skips files matched by the project's **root**
  `.gitignore`, keeping build artefacts and generated data out of the map on large repos. Honours a
  pragmatic, deterministic subset (comments/blanks, globs and `**`, leading `/` anchoring, trailing
  `/` directory-only, `!` negation; nested `.gitignore` files are not read). Applied consistently to
  the graph build, the manifest, and the freshness signature so staleness detection stays correct.
  Default off = byte-identical; zero new dependency (stdlib `re`/`fnmatch`).

### Note

Both are the on-brand, zero-weight pickups from a scan of the code-graph / repo-map / agent-memory
ecosystem (aider, RepoGraph, repomix/gitingest, mem0/A-MEM, ACT-R). The heavier ideas — tree-sitter
multi-language parsing, embeddings/vector memory, LLM-driven extract/update memory, a watcher
process, access-frequency reinforcement (mutable, non-deterministic state) — were deliberately left
out: they would break Second Brain's zero-dependency, read-only, deterministic, low-token core.
+21 tests.

## [0.8.1] - 2026-06-20

### Changed

- **In-process graph cache for the MCP server** — a long-running `second-brain-mcp` now reuses the
  loaded graph across tool calls within the freshness window instead of re-parsing `graph.json` and
  re-stat'ing every file on each call. On a ~130k-file repo this turns ~16s per query into an
  instant cache hit; outside the window it re-checks the content signature and reloads/rebuilds if
  the project changed. `clear_graph_cache()` resets it.
- **`SECOND_BRAIN_REFRESH_TTL` now defaults to 150s** (was 0 = check on every query). A one-shot
  CLI command still checks once; the throttle (and the cache above) matter for the long-running MCP
  server on large graphs. Set it to `0` to restore check-every-query.

## [0.8.0] - 2026-06-20

### Added

- **Symbol signatures in `focus`** — `focus --signatures` (and the MCP `focus` tool's
  `signatures=True`) appends the key function/class signatures of the top-ranked Python files, read
  on demand via the stdlib `ast` symbol layer. The assistant sees the API of the relevant files
  without opening them — the idea behind aider's repo map, in a zero-dependency, Python-only form.
  Off by default; plain `focus` output is unchanged.
- **Ranked, budgeted `impact`** — `impact` / `impact_diff` (CLI `--budget`, MCP `budget`) annotate
  each impacted node with its incident `degree` and, with a token budget, return the most useful
  ones first (nearest, then most-connected) trimmed to the budget — a hub with hundreds of
  dependents yields only the ones worth reviewing. Default (0) is unchanged: grouped by depth.
- **`view --focus "<task>"`** — renders exactly the slice `focus` would return, in the offline
  viewer, so a human can *see* the context an assistant receives. Reuses the existing viewer.
- **`schema_version`** in `graph.json` — the on-disk graph now carries a format version (additive,
  non-breaking; `from_dict` tolerates it) so exports, MCP and external tools can detect the format.

### Changed

- **Centralized budget accounting** — a new stdlib-only `budget.py` (`node_cost` / `text_cost` /
  `fit`) is the single place the query layer estimates token cost and fits a ranked list to a
  budget; `focus` and `impact` now share it. No behavioural change for existing callers.

### Note

On-brand, zero-dependency patterns absorbed from a study of **aider's repo map** (PageRank-ranked,
token-budgeted, signature-bearing) and the sibling project
**[galimar/veridge](https://github.com/galimar/veridge)** (centralized budget, ranked impact,
`view --focus`, versioned graph). The heavier ideas from that ecosystem — tree-sitter multi-language
parsing, embeddings/vector stores, a watcher process — were deliberately left out: they would break
Second Brain's zero-dependency, read-only, deterministic core. +8 tests (coverage 94%).

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
