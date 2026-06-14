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


class EdgeType(str, Enum):
    """The typology of an edge. Drives the edge color in the graph viewer."""

    IMPORTS = "imports"        # code A imports/uses B
    REFERENCES = "references"  # A cites B (markdown link, wikilink or path-in-prose)
    BELONGS_TO = "belongs_to"  # a node belongs to an area
    MENTIONS = "mentions"      # a document mentions a decision
    TOUCHES = "touches"        # a session/commit touched a file


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
}

EDGE_COLORS: dict[EdgeType, str] = {
    EdgeType.IMPORTS: "#16A34A",
    EdgeType.REFERENCES: "#D97706",
    EdgeType.BELONGS_TO: "#6B7280",
    EdgeType.MENTIONS: "#DC2626",
    EdgeType.TOUCHES: "#92400E",
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
        return True

    # -- queries ------------------------------------------------------------
    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def neighbors(self, node_id: str, direction: str = "both") -> list[str]:
        """Return ids of neighboring nodes. ``direction`` in {out, in, both}."""
        out = {e.target for e in self.edges if e.source == node_id}
        inc = {e.source for e in self.edges if e.target == node_id}
        if direction == "out":
            return sorted(out)
        if direction == "in":
            return sorted(inc)
        return sorted(out | inc)

    def degree(self, node_id: str) -> int:
        return sum(1 for e in self.edges if e.source == node_id or e.target == node_id)

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
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Graph:
        g = cls(project=d.get("project", ""))
        for nd in d.get("nodes", []):
            g.add_node(Node.from_dict(nd))
        for ed in d.get("edges", []):
            g.add_edge(Edge.from_dict(ed))
        return g
