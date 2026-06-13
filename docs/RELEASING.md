# Releasing to PyPI

The package builds cleanly and passes `twine check`. Publishing is a manual step done by the
maintainer with their own PyPI token (the build is reproducible; only the upload needs secrets).

## One-time setup

1. Create accounts on [PyPI](https://pypi.org/account/register/) and, for a dry run,
   [TestPyPI](https://test.pypi.org/account/register/).
2. Create an **API token** (PyPI → Account settings → API tokens). Use it as the password with
   username `__token__`, or put it in `~/.pypirc`.

## Build & validate (reproducible, no secrets)

```bash
python -m pip install --upgrade build twine
# from the repo root:
rm -rf dist           # PowerShell: Remove-Item dist -Recurse -Force
python -m build       # -> dist/second_brain_graph-<ver>-py3-none-any.whl + .tar.gz
python -m twine check dist/*
```

Both artifacts must report `PASSED`. They already include the vendored 3D viewer
(`second_brain/ui/3d-force-graph.min.js` + `template.html`) in both the wheel and the sdist, so
`second-brain view` works offline after a plain `pip install`.

## Dry run on TestPyPI (recommended for the first release)

```bash
python -m twine upload --repository testpypi dist/*
# then, in a fresh venv, verify it installs and runs:
pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ "second-brain-graph[mcp]"
second-brain --version
```

## Publish to PyPI

```bash
python -m twine upload dist/*
```

## Cutting a new version

1. Bump `__version__` in `second_brain/__init__.py` (the single source of truth; `pyproject.toml`
   reads it dynamically).
2. Commit, then tag: `git tag v<ver> && git push --tags`.
3. Build, check, and upload as above.

> Note: an automated GitHub Actions *publish-on-tag* workflow (PyPI Trusted Publishing) can be
> added later so tagging a release uploads it without a local token.
