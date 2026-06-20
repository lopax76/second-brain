"""Token-budget accounting for the query layer (zero-dependency, deterministic).

One place to estimate the token cost of a compact graph row and to fit a ranked list into a
budget — so ``focus`` and ``impact`` (and any future budgeted query) count tokens the same way.
The estimate is a deliberate, stable heuristic (about chars/4), never a model call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from second_brain.model import Node

T = TypeVar("T")


def node_cost(node: Node) -> int:
    """Rough token cost of a node's compact entry (id + type + path). chars/4 is an estimate."""
    chars = len(node.id) + len(node.type.value) + len(node.path or "") + 12
    return max(1, round(chars / 4))


def text_cost(text: str) -> int:
    """Rough token cost of a short text fragment (about chars/4, min 1)."""
    return max(1, round(len(text) / 4))


def fit(items: Iterable[T], cost: Callable[[T], int], budget: int) -> tuple[list[T], int, bool]:
    """Greedily admit ``items`` (already in priority order) until ``budget`` tokens are spent.

    Always admits at least the first item, so a tiny budget never yields nothing. Returns
    ``(kept, spent, truncated)``. ``budget <= 0`` keeps everything.
    """
    kept: list[T] = []
    spent = 0
    truncated = False
    for it in items:
        c = cost(it)
        if budget > 0 and kept and spent + c > budget:
            truncated = True
            break
        kept.append(it)
        spent += c
    return kept, spent, truncated


__all__ = ["node_cost", "text_cost", "fit"]
