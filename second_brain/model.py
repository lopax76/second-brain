"""Graph model for Second Brain: typed nodes, typed edges, and a small container.

The graph is intentionally simple and serializable to plain JSON: nodes are files or
logical entities (areas), edges are typed relationships between them. Colors are part of
the model so the viewer and any consumer share a single source of truth for them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["NodeType", "EdgeType", "NODE_COLORS", "EDGE_COLORS", "Node", "Edge", "Graph"]


class NodeType(str, Enum):
    """The typology of a node. Drives the node color in the graph viewer."""

    STRUCTURE = "structure"   # PROGETTO/README/ADR/foundation docs
    PROGRAM = "program"       # source code files
    REPORT = "report"         # reports / analyses / collaudo / diagnosi
    DESIGN = "design"         # designs / plans / specs
    DATA = "data"             # databases / datasets
    MEMORY = "memory"         # persistent memory files
    DECISION = "decision"     # recorded decisions
    CONFIG = "config"         # configuration files
    AREA = "area"             # logical cluster / container
    SESSION = "session"       # a work session / git commit
    SYMBOL = "symbol"         # a function/class inside a code file (opt-in symbol layer)


class EdgeType(str, Enum):
    """The typology of an edge. Drives the edge color in the graph viewer."""

    IMPORTS = "imports"        # code A imports/uses B
    REFERENCES = "references"  # A cites B (markdown link, wikilink or path-in-prose)
    BELONGS_TO = "belongs_to"  # a node belongs to an area
    MENTIONS = "mentions"      # a document mentions a decision
    TOUCHES = "touches"        # a session/commit touched a file
    DEFINES = "defines"        # a code file defines a symbol (function/class)
    CALLS = "calls"            # a symbol calls another symbol (same-file, conservative)


# Single source of truth for colors (matches docs/SB-design-brief.md).
NODE_COLORS: dict[NodeType, str] = {
    NodeType.STRUCTURE: "#1E3A8A",
    NodeType.PROGRAM: "#16A34A",
    NodeType.REPORT: "#D97706",
    NodeType.DESIGN: "#7C3AED",
    NodeType.DATA: "#0D9488",
    NodeType.MEMORY: "#DB2777",
    NodeType.DECISION: "#DC2626",
    NodeType.CONFIG: "#EA580C",
    NodeType.AREA: "#6B7280",
    NodeType.SESSION: "#92400E",
    NodeType.SYMBOL: "#0EA5E9",
}

EDGE_COLORS: dict[EdgeType, str] = {
    EdgeType.IMPORTS: "#16A34A",
    EdgeType.REFERENCES: "#D97706",
    EdgeType.BELONGS_TO: "#6B7280",
    EdgeType.MENTIONS: "#DC2626",
    EdgeType.TOUCHES: "#92400E",
    EdgeType.DEFINES: "#0EA5E9",
    EdgeType.CALLS: "#0284C7",
}


@dataclass
class Node:
    """A node in the project graph.

    ``id`` is stable and unique (the POSIX relative path for files, or ``area:<name>``
    for areas). ``path`` is the POSIX relative path for file-backed nodes, ``None`` for
    areas. ``description`` is a short human-readable explanation shown in the graph viewer.
    """

    id: str
    type: NodeType
    label: str
    description: str = ""
    path: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copy meta so a caller mutating their dict after construction can't corrupt this node.
        self.meta = dict(self.meta)

    def to_dict(self) -> dict[str, Any]:
        # Color is intentionally NOT persisted: it is derived from ``type`` via NODE_COLORS
        # (single source of truth), keeping the store small and drift-free.
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "description": self.description,
            "path": self.path,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Node:
        return cls(
            id=d["id"],
            type=NodeType(d["type"]),
            label=d["label"],
            description=d.get("description", ""),
            path=d.get("path"),
            meta=dict(d.get("meta", {})),
        )


@dataclass
class Edge:
    """A typed, directed edge from ``source`` to ``target`` (node ids)."""

    source: str
    target: str
    type: EdgeType
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.meta = dict(self.meta)  # defensive copy (see Node.__post_init__)

    def key(self) -> tuple[str, str, str]:
        """Identity used for de-duplication."""
        return (self.source, self.target, self.type.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Edge:
        return cls(
            source=d["source"],
            target=d["target"],
            type=EdgeType(d["type"]),
            meta=dict(d.get("meta", {})),
        )


class Graph:
    """A small, JSON-serializable container of nodes and edges."""

    def __init__(self, project: str = "") -> None:
        self.project = project
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        # Lazily-built adjacency index (out-neighbors, in-neighbors, incident-edge degree),
        # invalidated on add_edge. Makes neighbors()/degree() O(deg) instead of O(edges)/call.
        self._adj: tuple[dict[str, set[str]], dict[str, set[str]], dict[str, int]] | None = None

    # -- mutation -----------------------------------------------------------
    def add_node(self, node: Node) -> Node:
        """Add a node. If the id already exists it is kept (first wins) and returned."""
        existing = self.nodes.get(node.id)
        if existing is not None:
            return existing
        self.nodes[node.id] = node
        return node

    def add_edge(self, edge: Edge) -> bool:
        """Add an edge, de-duplicated by (source, target, type). Returns True if added."""
        k = edge.key()
        if k in self._edge_keys:
            return False
        self._edge_keys.add(k)
        self.edges.append(edge)
        self._adj = None  # invalidate the adjacency index
        return True

    def _adjacency(self) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, int]]:
        """Build (or reuse) the adjacency index: out-neighbors, in-neighbors, incident degree.

        ``degree`` counts incident *edges* (so two edge types between the same pair count twice,
        matching the old scan), and a self-loop counts once — identical to the previous behavior.
        """
        if self._adj is None:
            out_n: dict[str, set[str]] = {}
            in_n: dict[str, set[str]] = {}
            deg: dict[str, int] = {}
            for e in self.edges:
                out_n.setdefault(e.source, set()).add(e.target)
                in_n.setdefault(e.target, set()).add(e.source)
                deg[e.source] = deg.get(e.source, 0) + 1
                if e.target != e.source:  # a self-loop is one incident edge, not two
                    deg[e.target] = deg.get(e.target, 0) + 1
            self._adj = (out_n, in_n, deg)
        return self._adj

    # -- queries ------------------------------------------------------------
    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def neighbors(self, node_id: str, direction: str = "both") -> list[str]:
        """Return ids of neighboring nodes. ``direction`` in {out, in, both}."""
        out_n, in_n, _ = self._adjacency()
        out = out_n.get(node_id, set())
        inc = in_n.get(node_id, set())
        if direction == "out":
            return sorted(out)
        if direction == "in":
            return sorted(inc)
        return sorted(out | inc)

    def degree(self, node_id: str) -> int:
        return self._adjacency()[2].get(node_id, 0)

    def counts(self) -> dict[str, dict[str, int]]:
        """Counts by node type and edge type (string keys, for reporting)."""
        nt: dict[str, int] = {}
        et: dict[str, int] = {}
        for n in self.nodes.values():
            nt[n.type.value] = nt.get(n.type.value, 0) + 1
        for e in self.edges:
            et[e.type.value] = et.get(e.type.value, 0) + 1
        return {"nodes": nt, "edges": et}

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        # Deterministic order -> stable graph.json (clean git diffs, reproducible hashes).
        nodes = sorted(self.nodes.values(), key=lambda n: n.id)
        edges = sorted(self.edges, key=lambda e: (e.source, e.target, e.type.value))
        return {
            "project": self.project,
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        # Determinism comes from sorting nodes/edges (see to_dict) + stable meta insertion order;
        # keys are kept in their readable order (id first), not alphabetized.
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Graph:
        g = cls(project=d.get("project", ""))
        for nd in d.get("nodes", []):
            g.add_node(Node.from_dict(nd))
        for ed in d.get("edges", []):
            g.add_edge(Edge.from_dict(ed))
        return g
