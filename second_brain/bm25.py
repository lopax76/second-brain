"""BM25 lexical relevance over short structural documents (zero-dependency, deterministic).

Ranks a project's nodes against a task query for ``focus``: a node whose id / path / symbol name
carries the *rare, specific* terms of the task outranks one that matches only common terms. This is
classic Okapi BM25 — IDF x saturated term-frequency with length normalisation — in pure stdlib: no
model, no embeddings, no network. The score is identical on the same corpus every run.

Why BM25 and not a plain token count: the old seeding gave every matched token weight 1, so a hit on
a ubiquitous term ("test", "py") counted as much as a hit on a discriminating one ("pagerank",
"D-SEA-42"). BM25's IDF makes rare terms dominate, and its TF saturation stops a term repeated many
times from swamping the score — exactly the relevance signal a task->file anchor needs.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens of length >= 2 (snake_case splits into components)."""
    return [t for t in _TOKEN.findall(text.lower()) if len(t) >= 2]


class BM25:
    """An in-memory BM25 index over ``{doc_id: text}``. Build once, score many queries."""

    def __init__(self, docs: dict[str, str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tf: dict[str, Counter[str]] = {d: Counter(tokenize(t)) for d, t in docs.items()}
        self._len: dict[str, int] = {d: sum(tf.values()) for d, tf in self._tf.items()}
        n = len(self._tf)
        self.avgdl = (sum(self._len.values()) / n) if n else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf.values():
            df.update(tf.keys())
        # BM25+ IDF: always positive, so a term present in every document still contributes.
        self.idf: dict[str, float] = {
            t: math.log((n - c + 0.5) / (c + 0.5) + 1.0) for t, c in df.items()
        }

    def score(self, query: str | list[str], doc_id: str) -> float:
        """BM25 score of ``doc_id`` for ``query`` (0.0 if the document has none of the terms)."""
        qtoks = query if isinstance(query, list) else tokenize(query)
        tf = self._tf.get(doc_id)
        if tf is None:
            return 0.0
        dl = self._len[doc_id]
        norm = self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0.0))
        total = 0.0
        for t in qtoks:
            f = tf.get(t, 0)
            if f:
                total += self.idf.get(t, 0.0) * (f * (self.k1 + 1.0)) / (f + norm)
        return total

    def scores(self, query: str | list[str]) -> dict[str, float]:
        """``{doc_id: score}`` for every document with a non-zero score (deterministic)."""
        qtoks = query if isinstance(query, list) else tokenize(query)
        out: dict[str, float] = {}
        for d in self._tf:
            s = self.score(qtoks, d)
            if s > 0.0:
                out[d] = s
        return out


__all__ = ["BM25", "tokenize"]
