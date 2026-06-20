"""Deterministic recency weighting for recall (the ACT-R *base-level* dimension).

Human declarative memory ranks a fact by *base-level activation* — how recently and how often it
was used — on top of associative spreading activation. Second Brain already does the associative
part (personalised PageRank in ``focus``); this module adds the missing base-level signal, derived
from git history that is **already in the graph** (``session`` nodes carry the commit date, with
``touches`` edges to the files they changed). No new dependency, no new indexing, no extra weight.

Determinism is preserved by anchoring "now" to the **most recent commit in the graph**, never the
wall clock — so the same repository state always yields the same scores. The per-file score combines
recency and frequency in one exponential-decay sum (a recent touch counts ~1; more touches add up),
which is the practical analogue of ACT-R's base-level equation.
"""

from __future__ import annotations

from datetime import datetime

from second_brain.model import EdgeType, Graph, NodeType

__all__ = ["recency_scores", "blend"]


def _parse_iso(value: object) -> datetime | None:
    """Parse a git ``%aI`` ISO-8601 timestamp; anything unparseable -> ``None`` (skipped)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def recency_scores(graph: Graph, *, half_life_days: float = 30.0) -> dict[str, float]:
    """Return ``{file_id: recency_score in (0, 1]}`` derived from git ``session``/``touches``.

    For each file, sum ``0.5 ** (age_days / half_life)`` over the commits that touched it, where
    ``age_days`` is measured from the most recent commit in the graph (the deterministic anchor,
    not the wall clock). Recent and/or frequently-touched files score higher; the result is
    normalised so the top file is ``1.0``. Empty when the graph has no dated sessions (no git
    history) — callers then fall back to pure structural recall.
    """
    hl = half_life_days if half_life_days and half_life_days > 0 else 30.0
    dates: dict[str, datetime] = {}
    for nid, node in graph.nodes.items():
        if node.type is NodeType.SESSION:
            dt = _parse_iso(node.meta.get("date"))
            if dt is not None:
                dates[nid] = dt
    if not dates:
        return {}
    anchor = max(dates.values())

    raw: dict[str, float] = {}
    for e in graph.edges:
        if e.type is EdgeType.TOUCHES:
            dt = dates.get(e.source)
            if dt is None or e.target not in graph.nodes:
                continue
            age_days = (anchor - dt).total_seconds() / 86400.0
            if age_days < 0:
                age_days = 0.0  # commit after the anchor can't happen, but clamp defensively
            raw[e.target] = raw.get(e.target, 0.0) + 0.5 ** (age_days / hl)
    if not raw:
        return {}
    top = max(raw.values())
    if top <= 0:
        return {}
    return {nid: v / top for nid, v in raw.items()}


def blend(
    base: dict[str, float], recency: dict[str, float], weight: float
) -> dict[str, float]:
    """Convex-combine a base ranking with recency: ``(1-w)*base_norm + w*recency``.

    ``base`` (e.g. PageRank) is min-max normalised to ``[0, 1]`` first so the two signals are
    comparable; ``recency`` is already in ``[0, 1]``. ``weight`` is clamped to ``[0, 1]``. Nodes
    absent from ``recency`` contribute only their base term (recency 0). Returns a score per key in
    ``base`` (deterministic; the ranking order downstream stays stable via id tie-break).
    """
    w = 0.0 if weight < 0 else 1.0 if weight > 1 else float(weight)
    if w == 0.0 or not base:
        return dict(base)
    lo = min(base.values())
    hi = max(base.values())
    span = hi - lo
    out: dict[str, float] = {}
    for nid, v in base.items():
        bn = (v - lo) / span if span > 0 else 0.0
        out[nid] = (1.0 - w) * bn + w * recency.get(nid, 0.0)
    return out
