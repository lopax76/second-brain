"""Per-graph memo: what is derived from a loaded graph is computed once per graph, not per call.

The MCP server keeps a project's graph in memory between calls; PageRank, the BM25 index of the
node texts and the structural fingerprint depend only on that graph, yet were rebuilt at every
``focus`` and ``report`` (measured on a 127k-node project: PageRank 3.5 s, BM25 2.2 s each time).

Entries are keyed by the graph OBJECT (a rebuilt graph is a new object, so it never sees the old
values) and checked against the node and edge counts, so a graph mutated after the fact is
recomputed rather than served stale. Only a handful of graphs are kept (LRU); the memo holds a
strong reference to each, so an id is never reused while its entry lives.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from second_brain.model import Graph

T = TypeVar("T")

_MAX_GRAPHS = 6
_MEMO: OrderedDict[int, tuple[Graph, tuple[int, int], dict[Any, Any]]] = OrderedDict()


def per_graph(graph: Graph, key: Any, compute: Callable[[], T]) -> T:
    """``compute()`` once per (graph, key); later calls on the same unchanged graph reuse it."""
    shape = (len(graph.nodes), len(graph.edges))
    entry = _MEMO.get(id(graph))
    if entry is None or entry[0] is not graph or entry[1] != shape:
        entry = (graph, shape, {})
        _MEMO[id(graph)] = entry
        while len(_MEMO) > _MAX_GRAPHS:
            _MEMO.popitem(last=False)
    _MEMO.move_to_end(id(graph))
    values = entry[2]
    if key not in values:
        values[key] = compute()
    return values[key]


def clear() -> None:
    """Forget everything (tests, or after rebuilding a graph in place)."""
    _MEMO.clear()


__all__ = ["clear", "per_graph"]
