"""The anti-drift gate: refuses to call the brain "fine" while it is stale or broken.

Three signals, by severity:
- **broken** (error)   — a reference points inside the project but the target is missing.
- **stale**  (error)   — files changed/added/removed since the last build (rebuild needed).
- **orphans** (info)    — file nodes not connected by any import/reference edge (possibly
  forgotten, but often legitimately standalone, so they never fail the gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from second_brain.freshness import diff_manifest
from second_brain.model import EdgeType, Graph

__all__ = ["GateReport", "find_broken", "find_orphans", "evaluate"]


@dataclass
class GateReport:
    broken: list[tuple[str, str]] = field(default_factory=list)
    stale: dict[str, list[str]] = field(
        default_factory=lambda: {"added": [], "removed": [], "changed": []}
    )
    orphans: list[str] = field(default_factory=list)
    # Files the manifest could only compare by size+mtime, never by content: above
    # ``_CONTENT_HASH_CAP`` (or not a text type) no bytes are read, by design, so data-heavy
    # projects stay cheap. For these, "clean" means "the stamp did not move" — weaker than for
    # every other file, and previously not said out loud anywhere.
    stamp_only: list[str] = field(default_factory=list)

    @property
    def stale_count(self) -> int:
        return sum(len(v) for v in self.stale.values())

    @property
    def ok(self) -> bool:
        """True when there is nothing that must be fixed (broken/stale)."""
        return not self.broken and self.stale_count == 0

    def summary(self) -> str:
        added, removed, changed = self.stale["added"], self.stale["removed"], self.stale["changed"]
        lines = [
            f"broken references: {len(self.broken)}",
            f"stale files: {self.stale_count} (+{len(added)} / -{len(removed)} / ~{len(changed)})",
            f"orphans: {len(self.orphans)} (info)",
        ]
        if self.stamp_only:
            lines.append(
                f"checked by size+mtime only, not by content: {len(self.stamp_only)} (info)"
            )
            for rel in self.stamp_only[:5]:
                lines.append(f"  [stamp-only] {rel}")
        for src, tgt in self.broken[:20]:
            lines.append(f"  [broken] {src} -> {tgt}")
        return "\n".join(lines)


def find_broken(graph: Graph) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for n in graph.nodes.values():
        for t in n.meta.get("broken_refs", []):
            out.append((n.id, t))
    return sorted(out)


def find_orphans(graph: Graph) -> list[str]:
    """File nodes with no import/reference edge.

    Only file-backed nodes are considered (area and symbol nodes have no ``path`` and are
    excluded); area membership and git ``touches`` do not count as a knowledge connection.
    """
    connected: set[str] = set()
    for e in graph.edges:
        if e.type in (EdgeType.IMPORTS, EdgeType.REFERENCES):
            connected.add(e.source)
            connected.add(e.target)
    return sorted(
        n.id for n in graph.nodes.values()
        if n.path is not None and n.id not in connected
    )


def evaluate(
    graph: Graph,
    old_manifest: dict[str, str] | None,
    new_manifest: dict[str, str],
) -> GateReport:
    """Evaluate the gate. ``old_manifest`` None means "no baseline" -> no stale reported."""
    stale = (
        diff_manifest(old_manifest, new_manifest)
        if old_manifest is not None
        else {"added": [], "removed": [], "changed": []}
    )
    # A manifest value shaped "s<size>:m<mtime>" is a stat stamp, not a content digest: say so.
    stamp_only = sorted(
        rel for rel, v in new_manifest.items()
        if isinstance(v, str) and v.startswith("s") and ":m" in v
    )
    return GateReport(
        broken=find_broken(graph), stale=stale, orphans=find_orphans(graph),
        stamp_only=stamp_only,
    )
