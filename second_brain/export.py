"""Export the graph to interchange formats (GraphML). Pure stdlib, deterministic.

GraphML is XML understood by Gephi, yEd, Cytoscape, networkx, and most graph tooling — so the
Second Brain graph can be opened, laid out, or analysed outside the bundled viewer. Output is
deterministic (nodes/edges sorted like ``graph.json``) for clean diffs.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from second_brain.model import Graph

_KEYS = (
    ('<key id="d_type" for="node" attr.name="type" attr.type="string"/>'),
    ('<key id="d_label" for="node" attr.name="label" attr.type="string"/>'),
    ('<key id="d_path" for="node" attr.name="path" attr.type="string"/>'),
    ('<key id="e_type" for="edge" attr.name="type" attr.type="string"/>'),
)


def to_graphml(graph: Graph) -> str:
    """Return the graph as a GraphML (XML) document."""
    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        *(f"  {k}" for k in _KEYS),
        f"  <graph id={quoteattr(graph.project or 'project')} edgedefault=\"directed\">",
    ]
    for n in sorted(graph.nodes.values(), key=lambda x: x.id):
        out.append(f"    <node id={quoteattr(n.id)}>")
        out.append(f'      <data key="d_type">{escape(n.type.value)}</data>')
        out.append(f'      <data key="d_label">{escape(n.label)}</data>')
        if n.path:
            out.append(f'      <data key="d_path">{escape(n.path)}</data>')
        out.append("    </node>")
    for e in sorted(graph.edges, key=lambda x: (x.source, x.target, x.type.value)):
        out.append(f"    <edge source={quoteattr(e.source)} target={quoteattr(e.target)}>")
        out.append(f'      <data key="e_type">{escape(e.type.value)}</data>')
        out.append("    </edge>")
    out += ["  </graph>", "</graphml>", ""]
    return "\n".join(out)


__all__ = ["to_graphml"]
