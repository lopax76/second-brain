"""Content-hash freshness + the single-walk ``index`` entry point.

Hashing uses the standard-library BLAKE2b (fast, no dependency). For text files the hash is
computed on newline-normalized bytes so a CRLF<->LF flip (e.g. a git checkout on Windows)
does not look like a content change. The manifest is a small ``{relative_path: hash}`` map
stored next to the graph; diffing it against the current files tells the gate whether the
brain is still in sync with the project.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

from second_brain.extract import (
    CachedExtract,
    FileExtract,
    extract_text,
    is_extractable,
    read_bytes_capped,
)
from second_brain.ignore import load_ignore_patterns
from second_brain.indexer import build_graph, gitignore_rules_for, iter_files
from second_brain.model import Graph, NodeType

_CHUNK = 65536
# Above this size a text file is hashed raw instead of normalized: it bounds memory, and a
# CRLF flip on a huge file then reads as "changed" - a SAFE false positive for the gate
# (it never hides a real change), unlike loading a multi-hundred-MB file into RAM.
_NORMALIZE_CAP = 8_000_000

# Files hashed with normalized line endings (CRLF/CR -> LF) to avoid cross-platform churn.
_TEXT_HASH_EXTS = {
    ".md", ".markdown", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".html",
    ".htm", ".css", ".sql", ".ps1", ".psm1", ".sh", ".bash", ".go", ".rs", ".java", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".cs",
}
# Content-hash text source/docs up to this size; data, binaries and larger files use a cheap
# size+mtime signature instead (no bytes read) so indexing stays light on data-heavy projects.
_CONTENT_HASH_CAP = 1_000_000


__all__ = ["file_hash", "build_manifest", "index", "index_cached", "BuildResult",
           "diff_manifest", "fast_signature", "is_stale", "auto_refresh_enabled",
           "load_or_refresh"]


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def file_hash(path: Path, *, normalize_newlines: bool = False) -> str:
    """Return a short, stable content hash of a file.

    With ``normalize_newlines`` the bytes are read whole and CRLF/CR collapsed to LF before
    hashing (correct across chunk boundaries); otherwise the file is streamed in chunks.
    """
    h = hashlib.blake2b(digest_size=16)
    if normalize_newlines and path.stat().st_size <= _NORMALIZE_CAP:
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        h.update(data)
    else:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
    return h.hexdigest()


def _hash_rel(root: Path, rel: str) -> str | None:
    """Freshness signature for a file.

    Source/doc/config text up to ``_CONTENT_HASH_CAP`` is content-hashed with newline
    normalization (precise and cross-platform stable). Data, binaries and large files use a cheap
    ``size+mtime`` signature - no bytes are read - so indexing stays fast on data-heavy projects.
    """
    p = root / rel
    try:
        st = p.stat()
    except OSError:
        return None
    if _ext(rel) in _TEXT_HASH_EXTS and st.st_size <= _CONTENT_HASH_CAP:
        try:
            return file_hash(p, normalize_newlines=True)
        except OSError:
            return None
    # Nanoseconds, not whole seconds. With `m{int(st.st_mtime)}` two different contents of the same
    # length written inside one second produced the SAME stamp, so `gate` — which recomputes this
    # very value — reported clean over a changed file. st_mtime_ns costs nothing extra and removes
    # that collision; what remains is a replacement that preserves size AND exact mtime (cp -p,
    # tar -x, a restore), which no stat-based check can see. Callers are told: see gate's report.
    return f"s{st.st_size}:m{st.st_mtime_ns}"


def build_manifest(root: str | os.PathLike[str]) -> dict[str, str]:
    """Return ``{relative_path: hash}`` for every indexable file under ``root``."""
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p), gitignore_rules_for(root_p))
    out: dict[str, str] = {}
    for rel in rels:
        hv = _hash_rel(root_p, rel)
        if hv is not None:
            out[rel] = hv
    return out


def _digest_bytes(data: bytes) -> str:
    """Digest raw bytes exactly as :func:`file_hash` would with ``normalize_newlines=True``.

    Same algorithm, same normalization — so a digest taken from bytes already in hand is
    interchangeable with the manifest value :func:`_hash_rel` computes for the same file.
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return h.hexdigest()


def _hashes_content(rel: str, size: int) -> bool:
    """Whether :func:`_hash_rel` would produce a real content digest for this file."""
    return _ext(rel) in _TEXT_HASH_EXTS and size <= _CONTENT_HASH_CAP


# SB's own configuration files. They are excluded from the walk (DEFAULT_IGNORE_FILES), so they
# never appeared in the signature — yet the graph depends on them: the `classify` block decides
# node types, and `respect_gitignore` decides which files exist at all. Editing `.secondbrain.json`
# therefore left a stale graph that reported itself fresh, with `gate` green, for ever. The keys are
# prefixed with ':' so they cannot collide with a relative path.
_CONFIG_INPUTS = (".secondbrain.json", ".secondbrainignore")

# Recorded in the signature for a file that exists but could not be read this time round — a file
# held open exclusively by an editor, by Excel, by an antivirus, by a log writer. Both the stored
# signature and a fresh one use it, so a file that STAYS unreadable does not cause endless
# rebuilding; but the moment it becomes readable the two differ and the build is retried. Omitting
# it, as before, made both sides agree on nothing and the lost edges stuck for good.
UNREADABLE = "!unreadable"


def config_signature(root: str | os.PathLike[str]) -> dict[str, str]:
    """Digest SB's own config files, so changing one counts as the project changing."""
    root_p = Path(root)
    out: dict[str, str] = {}
    for name in _CONFIG_INPUTS:
        p = root_p / name
        try:
            out[f":config:{name}"] = file_hash(p, normalize_newlines=True) if p.is_file() else "-"
        except OSError:
            out[f":config:{name}"] = "?"  # unreadable: never matches, so it re-checks next time
    return out


@dataclass
class BuildResult:
    """Everything one build produces — pass it straight to :func:`second_brain.store.save`."""

    graph: Graph
    manifest: dict[str, str]
    extract: dict[str, CachedExtract]
    signature: dict[str, str]


def index_cached(
    root: str | os.PathLike[str],
    *,
    operational: bool = True,
    symbols: bool = False,
    incremental: bool = True,
    stats: dict[str, int] | None = None,
) -> BuildResult:
    """Build the graph and the manifest, reusing what the last build already learned.

    Returns a :class:`BuildResult`; hand its ``extract`` and ``signature`` to
    :func:`second_brain.store.save` so the next build can reuse them in turn.

    The freshness signature is produced by *this* walk rather than by a separate
    :func:`fast_signature` pass. Two walks over a 5.000-file tree cost about a second of pure
    duplicated ``stat`` — and the ordering guarantee is unchanged, because the signature is still
    captured before any file's contents are read: a file that appears afterwards is missing from
    the stored signature, so the next query sees a mismatch and rebuilds (false-stale, safe).

    Exactly one thing is reused, and only against fresh evidence: the **extraction** (imports,
    reference targets, symbols) of a file whose key still matches the one it was stored under —
    a content digest taken from the very bytes the findings came from — or, above the content-hash
    cap, the precise ``size:mtime_ns`` signature. The manifest is recomputed
    from the files every time: it is what ``gate`` compares against, so it has to be evidence
    rather than memory, and a rebuild has to be able to heal a drifted store, not re-confirm it.

    Resolution is never reused: :func:`build_graph` re-resolves every reference in the project on
    every call, so adding or deleting a file still updates every other file's edges. That is what
    makes an incremental result identical to a full rebuild rather than merely close to one — with
    one stated exception: above the content-hash cap the key is stat evidence, so a replacement
    preserving both size and exact mtime is invisible here while a full rebuild would re-extract.
    See the note in :mod:`second_brain.extract`.

    ``incremental=False`` ignores the stored state entirely and rebuilds from scratch. Pass a
    dict as ``stats`` to receive ``{files, hashed, extracted, reused}`` for reporting.
    """
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p), gitignore_rules_for(root_p))

    from second_brain import store
    cached = store.load_extract(root_p) if incremental else {}

    # 1. One stat per file: it produces the freshness signature and the sizes used below.
    #    Seeded with SB's own config files, which the walk excludes but the graph depends on.
    signature: dict[str, str] = dict(config_signature(root_p))
    sizes: dict[str, int] = {}
    present: list[str] = []
    for rel in rels:
        path = root_p / rel
        try:
            st = path.stat()
        except OSError:
            # Cannot stat. Two very different reasons, and they must not be conflated:
            #   * the entry is GONE (deleted between the walk and now) -> it must not become a node;
            #   * the entry EXISTS but cannot be followed — a dangling symlink, which is exactly
            #     what a git clone of a symlinked AGENTS.md/CLAUDE.md leaves on Windows, or a file
            #     momentarily locked. Those are real directory entries that other documents link
            #     to, and dropping them would silently turn those links into broken references.
            # os.path.lexists answers this without following the link.
            if os.path.lexists(path):
                present.append(rel)
                signature[rel] = UNREADABLE  # retried as soon as it can be stat'ed again
            continue
        signature[rel] = f"{st.st_size}:{st.st_mtime_ns}"
        sizes[rel] = st.st_size
        present.append(rel)
    # A file listed by the walk but gone by now must not become a node: it used to stay in the
    # graph with its edges while being absent from both signature and manifest, so the next walk
    # could not notice it and `gate` stayed green over a phantom that never went away.
    rels = present

    # 2 + 3. Manifest and extraction, from a SINGLE read per extractable file.
    #
    # These used to be two passes: hash everything, then open the files that changed. That meant
    # the digest and the extraction came from two different reads at two different instants, and a
    # file edited in between got stored as "digest of version X, findings of version Y". When the
    # file then settled on X — the common case, because the digest pass ran first — every later
    # build recomputed X, matched the cache, and served Y's findings again. Permanently, with
    # `gate` green: gate compares digests with digests, and those agreed.
    #
    # Now the bytes are read once and both the digest and the findings come from *those* bytes, so
    # a mislabelled entry is not merely unlikely, it is unrepresentable.
    manifest: dict[str, str] = {}
    extracts: dict[str, FileExtract] = {}
    fresh_cache: dict[str, CachedExtract] = {}
    hashed = extracted = reused = 0

    for rel in rels:
        # 0 for an entry that exists but could not be stat'ed (dangling symlink, locked file):
        # the reads below then fail too, so it stays a node with no size and no edges — which is
        # exactly what a from-scratch build produces for it.
        size = sizes.get(rel, 0)
        extractable = is_extractable(rel)

        if not extractable:
            hashed += 1
            hv = _hash_rel(root_p, rel)  # never opens data/binaries: stat-only stamp
            if hv is not None:
                manifest[rel] = hv
            continue

        entry = cached.get(rel)
        data: bytes | None = None
        if _hashes_content(rel, size):
            # Text within the cap: one read serves the manifest digest, the cache key and, if
            # needed, the parse.
            data = read_bytes_capped(root_p / rel)
            if data is None:
                # Stat worked but the read did not: a locked file. Its edges are missing from this
                # build, so do not let the signature call it settled — otherwise the loss is
                # permanent and invisible.
                hashed += 1
                hv = _hash_rel(root_p, rel)
                if hv is not None:
                    manifest[rel] = hv
                signature[rel] = UNREADABLE
                continue
            hashed += 1
            key: str | None = _digest_bytes(data)
            manifest[rel] = key
        else:
            # Above the cap the manifest is a coarse stamp by design ("no bytes are read", so
            # data-heavy projects stay cheap). Re-reading a 50 MB log on every build just to key
            # the cache would throw that away, so the key is the PRECISE size+mtime_ns signature
            # instead — exactly the evidence `is_stale` already trusts to decide whether to
            # rebuild at all, and unaffected by the same-second collision the coarse stamp has.
            hashed += 1
            hv = _hash_rel(root_p, rel)
            if hv is not None:
                manifest[rel] = hv
            key = signature.get(rel)

        fe: FileExtract | None = None
        if entry is not None and key is not None and entry.hash == key:
            if entry.data.has_symbols or not symbols:
                fe = entry.data
                reused += 1
        if fe is None:
            extracted += 1
            if data is None:
                data = read_bytes_capped(root_p / rel)
            if data is not None:
                fe = extract_text(rel, data.decode("utf-8", errors="ignore"), symbols=symbols)
        if fe is None:
            continue
        extracts[rel] = fe
        if key is not None:
            fresh_cache[rel] = CachedExtract(hash=key, data=fe)

    if stats is not None:
        stats.update({"files": len(rels), "hashed": hashed,
                      "extracted": extracted, "reused": reused})

    graph = build_graph(root_p, symbols=symbols, _rels=rels, _extract=extracts)
    if operational:
        from second_brain.operational import enrich
        enrich(graph, root_p)
    return BuildResult(graph=graph, manifest=manifest, extract=fresh_cache, signature=signature)


def index(
    root: str | os.PathLike[str], *, operational: bool = True, symbols: bool = False
) -> tuple[Graph, dict[str, str]]:
    """Build the graph and the manifest from one directory walk.

    Thin wrapper over :func:`index_cached` for callers that do not persist the extraction cache;
    the build is still incremental if a cache is present on disk.
    """
    res = index_cached(root, operational=operational, symbols=symbols)
    return res.graph, res.manifest


def diff_manifest(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """Return ``{added, removed, changed}`` between two manifests (sorted lists)."""
    old_k, new_k = set(old), set(new)
    return {
        "added": sorted(new_k - old_k),
        "removed": sorted(old_k - new_k),
        "changed": sorted(k for k in (old_k & new_k) if old[k] != new[k]),
    }


# -- self-refreshing reads ---------------------------------------------------------------------
# A query should never answer from a stale map. Instead of re-hashing every file on each query
# (expensive on big repos), we keep a cheap signature — size+mtime per file, stat() only, no
# bytes read — and rebuild only when it differs. This makes "always fresh" the default behavior
# of the tool itself, with no external scheduler and no dependencies.

_OFF_VALUES = {"0", "false", "no", "off"}
# Throttle: in a long-running server, re-stat'ing every file on every query costs O(files).
# With SECOND_BRAIN_REFRESH_TTL=<seconds> the staleness check is skipped if it ran within that
# window for the same project. Default 0 = always check (freshness-first). Per-repo graphs (the
# recommended layout) keep the check cheap; raise the TTL only for a huge single monorepo graph.
_LAST_CHECK: dict[str, float] = {}


def fast_signature(root: str | os.PathLike[str]) -> dict[str, str]:
    """Cheap per-file signature ``{relpath: "size:mtime_ns"}`` using stat only (no file reads).

    ``st_mtime_ns`` (nanoseconds) is used rather than whole seconds so an edit made shortly after
    a build is still detected; the only blind spot is a same-size edit within the *same filesystem
    tick* as the build (a real but very narrow window — ``second-brain gate``'s content-hash check
    catches it exactly).
    """
    root_p = Path(root).resolve()
    rels = iter_files(root_p, load_ignore_patterns(root_p), gitignore_rules_for(root_p))
    out: dict[str, str] = dict(config_signature(root_p))
    for rel in rels:
        try:
            st = (root_p / rel).stat()
        except OSError:
            out[rel] = UNREADABLE
            continue
        out[rel] = f"{st.st_size}:{st.st_mtime_ns}"
    return out


def is_stale(root: str | os.PathLike[str]) -> bool:
    """True if the project changed since the stored signature (or there is no signature yet)."""
    from second_brain import store
    old = store.load_signature(root)
    if old is None:
        return True  # no baseline -> rebuild once (which writes the signature)
    return old != fast_signature(root)


def auto_refresh_enabled() -> bool:
    """Whether self-refreshing reads are on (env ``SECOND_BRAIN_AUTO_REFRESH``, default on)."""
    return os.environ.get("SECOND_BRAIN_AUTO_REFRESH", "1").strip().lower() not in _OFF_VALUES


def _refresh_ttl() -> float:
    try:
        ttl = float(os.environ.get("SECOND_BRAIN_REFRESH_TTL", "150"))
    except ValueError:
        return 0.0
    return max(0.0, ttl) if math.isfinite(ttl) else 0.0  # inf/nan -> always check (never freeze)


def _should_check(root: str | os.PathLike[str]) -> bool:
    """Throttle the staleness check to at most once per TTL window per project (if TTL > 0)."""
    ttl = _refresh_ttl()
    if ttl <= 0:
        return True
    key = str(Path(root).resolve())
    now = time.monotonic()
    last = _LAST_CHECK.get(key)
    if last is not None and (now - last) < ttl:
        return False
    _LAST_CHECK[key] = now
    return True


def _has_symbols(graph: Graph) -> bool:
    return any(n.type is NodeType.SYMBOL for n in graph.nodes.values())


def _save_quiet(
    root: str | os.PathLike[str], g: Graph, m: dict[str, str], *,
    symbols: bool, signature: dict[str, str],
    extract: dict[str, CachedExtract] | None = None,
) -> None:
    """Persist the store, ignoring write errors (read-only checkout / locked store)."""
    from second_brain import store
    try:
        store.save(root, g, m, signature=signature, symbols=symbols, extract=extract)
    except OSError:
        pass  # degrade gracefully: the in-memory graph is still served


def load_or_refresh(
    root: str | os.PathLike[str], *, refresh: bool | None = None
) -> Graph:
    """Return the project graph, rebuilt **iff** the project changed since the last build.

    This is the read path for every query: it auto-builds on first touch and silently refreshes
    a stale store before answering, so an assistant always sees the current project — including
    *uncommitted* edits — without a manual rebuild. The staleness check is a stat-only signature
    diff (cheap). Set ``refresh=False`` (or env ``SECOND_BRAIN_AUTO_REFRESH=0``) to serve the
    stored graph as-is; ``SECOND_BRAIN_REFRESH_TTL=<seconds>`` throttles the check on huge graphs.
    The rebuild preserves the stored mode (file-level or ``--symbols``), and a store write that
    fails (read-only checkout) degrades to serving the in-memory graph instead of crashing.
    """
    from second_brain import store
    if refresh is None:
        refresh = auto_refresh_enabled()

    g = store.load_graph(root)
    if g is None:  # first touch: build + persist (graph, manifest, signature, mode)
        # Capture the signature BEFORE reading file contents: if a file changes during the walk,
        # the stored signature is then "older" than the change, so the next query sees a mismatch
        # and rebuilds (false-stale = safe) — instead of a permanent false-fresh.
        res = index_cached(root)  # its own walk also yields the signature (no second pass)
        _save_quiet(root, res.graph, res.manifest, symbols=False,
                    signature=res.signature, extract=res.extract)
        return res.graph
    if refresh and _should_check(root) and is_stale(root):
        # Prefer the persisted build mode; fall back to "are there symbol nodes?" only if the
        # store predates mode.json (so a --symbols build of a then-symbol-less tree is preserved).
        mode = store.load_symbols_mode(root)
        use_symbols = mode if mode is not None else _has_symbols(g)
        try:
            res = index_cached(root, symbols=use_symbols)
        except Exception:
            return g  # any rebuild failure -> serve the loaded graph (stale but alive), never crash
        _save_quiet(root, res.graph, res.manifest, symbols=use_symbols,
                    signature=res.signature, extract=res.extract)
        return res.graph
    return g
