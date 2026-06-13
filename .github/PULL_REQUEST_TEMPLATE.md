<!-- Thanks for contributing! Keep PRs focused on one logical change. -->

## What & why

<!-- What does this change, and what problem does it solve? Link any related issue. -->

## How I verified it

- [ ] `ruff check secondbrain tests` passes
- [ ] `pytest -q` passes
- [ ] Added/updated tests for the change

## Design checklist

- [ ] Read-only on sources (nothing written outside `.secondbrain/`)
- [ ] Core stays dependency-free (new deps, if any, are behind an optional extra)
- [ ] No file contents pushed into query results / the graph
- [ ] Output stays deterministic (stable ordering)
