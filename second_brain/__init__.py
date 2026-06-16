"""Second Brain (SB) — a living, low-token map of every project.

Public API re-exports the graph model so callers can do ``from second_brain import Graph``.
"""

from __future__ import annotations

from second_brain.model import EDGE_COLORS, NODE_COLORS, Edge, EdgeType, Graph, Node, NodeType

__version__ = "0.6.1"

__all__ = [
    "EDGE_COLORS",
    "NODE_COLORS",
    "Edge",
    "EdgeType",
    "Graph",
    "Node",
    "NodeType",
    "__version__",
]
