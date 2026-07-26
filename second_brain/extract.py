"""Per-file raw extraction, cacheable between builds — the basis of incremental indexing.

Indexing splits cleanly into two halves:

* **extraction** — open one file and pull out its raw imports / reference targets / symbols.
  It depends on that file alone, so its result can be stored and reused whenever the file has
  not changed. Essentially *all* of the indexing cost lives here: reading bytes and parsing.
* **resolution** — turn those raw targets into edges against the whole project's file set.
  It is cheap (dictionary lookups) but irreducibly **global**: adding or deleting a single file
  can make some *other* file's reference start resolving, or go broken.

An incremental build therefore re-extracts only what changed and **re-resolves everything, every
time**. That is what makes an incremental result byte-identical to a full rebuild, and it is why
the usual objection to incremental graph updates — a stale cross-file edge quietly surviving a
partial update — does not apply here: no edge is ever carried over, only raw per-file findings.

The cache lives in ``.secondbrain/extract.json``, is keyed by the same content hash the manifest
already computes, and is derived data like everything else in the store: deleting it costs one
full rebuild, never correctness.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from second_brain.pycode import PyImport, js_imports, python_imports
from second_brain.pysymbols import Def
from second_brain.pysymbols import extract as extract_symbol_calls
from second_brain.references import extract_references_tagged

__all__ = ["CACHE_VERSION", "cache_id", "FileExtract", "extract_file", "extract_text",
           "read_bytes_capped", "is_extractable", "cache_to_json", "cache_from_json"]

# Bumped when the SHAPE of a stored entry changes. It deliberately does not try to describe the
# *meaning* of an extraction: see cache_id().
CACHE_VERSION = 2


def cache_id() -> str:
    """Identity a stored cache must match to be reusable: shape version + SB version.

    Keying an entry on the file's content alone says what was read, never **who read it** — so a
    release that changes what an extractor finds (this one rewrote ``python_imports``) would serve
    the old findings forever for every file already cached, with ``gate`` green, if whoever wrote
    the release forgot to bump a hand-maintained constant. Binding the identity to
    ``second_brain.__version__`` removes the need to remember: any released change invalidates the
    cache, and the cost of being wrong is one full rebuild.
    """
    from second_brain import __version__
    return f"{CACHE_VERSION}-{__version__}"

_JS_EXTS = {".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"}
_DOC_REF_EXTS = {".md", ".markdown", ".rst", ".txt", ".html", ".htm"}
# Mirrors indexer._TEXT_EXTS for the file types we actually open; kept here so extraction is
# self-contained and the indexer no longer needs to know how to read a file.
_MAX_READ_BYTES = 5_000_000


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def is_extractable(rel: str) -> bool:
    """True if this file type can produce edges at all (decided from the extension alone).

    Everything else — data, config, binaries — is never opened by the indexer, so it has
    nothing to cache and costs no I/O either way.
    """
    ext = _ext(rel)
    return ext == ".py" or ext in _JS_EXTS or ext in _DOC_REF_EXTS


@dataclass
class FileExtract:
    """Everything the indexer needs from one file's *contents*, before resolution."""

    py_imports: tuple[PyImport, ...] = ()
    js_specs: tuple[str, ...] = ()
    refs: tuple[tuple[str, str], ...] = ()          # (target, kind)
    sym_defs: tuple[Def, ...] = ()
    sym_calls: tuple[tuple[str, str], ...] = ()
    has_symbols: bool = False                       # was this extracted in --symbols mode?

    def to_json(self) -> dict[str, Any]:
        """Compact dict — empty fields are omitted so the cache stays small on big trees."""
        out: dict[str, Any] = {}
        if self.py_imports:
            out["p"] = [[i.level, i.module, list(i.names)] for i in self.py_imports]
        if self.js_specs:
            out["j"] = list(self.js_specs)
        if self.refs:
            out["r"] = [[t, k] for t, k in self.refs]
        if self.has_symbols:
            out["y"] = 1
            if self.sym_defs:
                out["s"] = [[d.qualname, d.kind, d.line] for d in self.sym_defs]
            if self.sym_calls:
                out["c"] = [[a, b] for a, b in self.sym_calls]
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> FileExtract:
        return cls(
            py_imports=tuple(
                PyImport(level=int(x[0]), module=x[1], names=tuple(x[2]))
                for x in d.get("p", [])
            ),
            js_specs=tuple(d.get("j", [])),
            refs=tuple((x[0], x[1]) for x in d.get("r", [])),
            sym_defs=tuple(
                Def(qualname=x[0], kind=x[1], line=int(x[2])) for x in d.get("s", [])
            ),
            sym_calls=tuple((x[0], x[1]) for x in d.get("c", [])),
            has_symbols=bool(d.get("y")),
        )


@dataclass
class CachedExtract:
    """A stored extraction plus the content hash it was taken from."""

    hash: str
    data: FileExtract = field(default_factory=FileExtract)


def read_bytes_capped(path: Path) -> bytes | None:
    """Read a file whole, or ``None`` if it is too large / unreadable.

    Returns raw bytes rather than text so a caller can both digest and decode **the same bytes**.
    Deciding the size cap from the bytes actually read (not from a separate ``stat``) is what keeps
    the digest and the extraction describing the same thing: a cap checked against a raw ``stat``
    while the digest was taken over newline-normalized bytes compared two different quantities, so
    one digest could match both a file that gets extracted and a file that gets refused.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return None if len(data) > _MAX_READ_BYTES else data


def extract_text(rel: str, text: str, *, symbols: bool = False) -> FileExtract:
    """Pull the raw findings out of already-read text. No I/O: the caller owns the read."""
    ext = _ext(rel)
    fe = FileExtract(has_symbols=symbols)
    if ext == ".py":
        fe.py_imports = tuple(python_imports(text))
        if symbols:
            defs, calls = extract_symbol_calls(text)
            fe.sym_defs = tuple(defs)
            fe.sym_calls = tuple(calls)
    elif ext in _JS_EXTS:
        fe.js_specs = tuple(js_imports(text))
    if ext in _DOC_REF_EXTS:
        fe.refs = tuple(extract_references_tagged(text))
    return fe


def extract_file(root: Path, rel: str, *, symbols: bool = False) -> FileExtract | None:
    """Read one file and return its raw findings, or ``None`` if not extractable/readable.

    ``None`` means "produces no edges and was not opened" — the caller stores nothing for it.
    """
    if not is_extractable(rel):
        return None
    data = read_bytes_capped(root / rel)
    if data is None:
        return None
    return extract_text(rel, data.decode("utf-8", errors="ignore"), symbols=symbols)


def cache_to_json(cache: dict[str, CachedExtract]) -> dict[str, Any]:
    """Serialize the whole cache (identity-stamped)."""
    return {
        "version": cache_id(),
        "files": {rel: {"h": ce.hash, **ce.data.to_json()} for rel, ce in sorted(cache.items())},
    }


def _str_pairs(value: Any, width: int) -> list[list[str]] | None:
    """Validate a list of fixed-width string rows; ``None`` if anything is off."""
    if not isinstance(value, list):
        return None
    out: list[list[str]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != width:
            return None
        if not all(isinstance(c, str) for c in row):
            return None
        out.append(row)
    return out


def _validate(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Strictly type-check one stored entry; ``None`` means "re-extract this file".

    Shape checks alone were not enough. ``from_json`` coerces the two integers but passed every
    other value straight through, so a poisoned entry — a numeric reference target, a nested list
    where a string belongs — survived parsing and only exploded much later inside reference
    resolution, far from any guard. Anything that is not exactly the expected type is refused here.
    """
    py = entry.get("p", [])
    if not isinstance(py, list):
        return None
    for imp in py:
        if not isinstance(imp, list) or len(imp) != 3:
            return None
        level, module, names = imp
        if not isinstance(level, int) or isinstance(level, bool):
            return None
        if module is not None and not isinstance(module, str):
            return None
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return None

    js = entry.get("j", [])
    if not isinstance(js, list) or not all(isinstance(s, str) for s in js):
        return None

    if _str_pairs(entry.get("r", []), 2) is None:
        return None
    if _str_pairs(entry.get("c", []), 2) is None:
        return None

    for d in entry.get("s", []):
        if not isinstance(d, list) or len(d) != 3:
            return None
        qual, kind, line = d
        if not (isinstance(qual, str) and isinstance(kind, str)):
            return None
        if not isinstance(line, int) or isinstance(line, bool):
            return None
    return entry


def cache_from_json(data: Any) -> dict[str, CachedExtract]:
    """Parse a stored cache; anything unexpected yields an empty cache (one full rebuild)."""
    if not isinstance(data, dict) or data.get("version") != cache_id():
        return {}
    files = data.get("files")
    if not isinstance(files, dict):
        return {}
    out: dict[str, CachedExtract] = {}
    for rel, entry in files.items():
        if not (isinstance(rel, str) and isinstance(entry, dict)):
            continue
        h = entry.get("h")
        if not isinstance(h, str) or _validate(entry) is None:
            continue
        try:
            out[rel] = CachedExtract(hash=h, data=FileExtract.from_json(entry))
        except (TypeError, ValueError, IndexError, KeyError):
            continue  # one unreadable entry -> re-extract that file, not the whole project
    return out
