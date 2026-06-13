# Contributing to Second Brain

Thanks for your interest! Second Brain is a small, focused tool and contributions are
welcome — bug reports, docs, and well-scoped pull requests alike.

## Design principles (please keep these intact)

These constraints are the point of the project, not incidental. PRs that break them are
unlikely to be merged:

- **Read-only on sources.** The tool indexes a project; it must never modify the files it
  scans. Everything it writes lives under `.secondbrain/`.
- **Files are the truth.** The graph is derived and always regenerable. Never duplicate file
  contents into the graph.
- **Zero runtime dependencies in the core.** `second_brain/` (everything except the optional
  MCP server) must run on the Python standard library alone. Optional features go behind an
  extra (e.g. `[mcp]`).
- **Low token cost.** Query results return ids, types, sizes and connections — never file
  contents. Don't add anything that would push the whole graph into an assistant's context.
- **Deterministic output.** `graph.json` and query results must be stably ordered so diffs
  and hashes are reproducible.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

## Before you open a PR

Run the same checks CI runs — both must be green:

```bash
ruff check second-brain tests
pytest -q
```

- **Write a test first.** The project is developed test-first; new behavior should come with
  a test, and bug fixes with a regression test.
- **Type hints** on public functions; keep modules small and single-purpose.
- **Identifiers in English**, prose/docstrings may be English or Italian to match the file
  you're editing.

## Pull requests

- Keep PRs focused — one logical change per PR.
- Describe the motivation and what you verified.
- Link any related issue.

## Reporting bugs and proposing features

Use the issue templates. For a bug, the most useful thing you can give us is a **minimal
project that reproduces it** (a handful of files is plenty) plus the command you ran and what
you expected.

## Security

Please do not file public issues for security problems — see [SECURITY.md](SECURITY.md).
