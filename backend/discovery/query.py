"""Queries on a dependency_graph contract (plain dict), for P2/P4 and the CLI.

impacted_by: "which positions depend on this component, and through which paths?"
explain:     five-layer text view of one position, with the evidence behind each edge.
"""

from __future__ import annotations

from collections import defaultdict, deque

from backend.discovery.graph import CONFIDENCE_RANK


def _out(graph: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in graph["edges"]:
        out[e["source"]].append(e)
    return out


def paths(graph: dict, start: str, goal: str, max_depth: int = 10, limit: int = 5) -> list[list[dict]]:
    """Shortest simple dependency paths start -> ... -> goal (breadth-first, at most `limit`)."""
    out, found = _out(graph), []
    queue: deque[tuple[str, list[dict]]] = deque([(start, [])])
    while queue and len(found) < limit:
        node, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        on_path = {start, *(e["target"] for e in path)}
        for e in out[node]:
            if e["target"] in on_path:
                continue
            if e["target"] == goal:
                found.append(path + [e])
                if len(found) >= limit:
                    break
            else:
                queue.append((e["target"], path + [e]))
    return found


def impacted_by(graph: dict, component: str, max_depth: int = 10, limit: int = 5) -> list[dict]:
    if component not in {n["id"] for n in graph["nodes"]}:
        raise KeyError(f"{component} is not a node of graph {graph['graph_id']}")
    rows = []
    for node in sorted(n["id"] for n in graph["nodes"] if n["type"] == "position"):
        found = paths(graph, node, component, max_depth, limit)
        if not found:
            continue
        rows.append(
            {
                "position_id": node.split(":", 1)[1],
                "paths": [
                    {
                        "nodes": [p[0]["source"]] + [e["target"] for e in p],
                        "edges": [e["id"] for e in p],
                        "relations": [e["relation"] for e in p],
                        "channels": [e["risk_channel"] for e in p],
                        "confidence": min((e["confidence"] for e in p), key=CONFIDENCE_RANK.__getitem__),
                    }
                    for p in found
                ],
            }
        )
    return rows


def explain(graph: dict, position_id: str) -> str:
    coverage = (graph.get("coverage") or {}).get(position_id)
    if coverage is None:
        return f"no coverage recorded for {position_id}"
    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    lines = [f"{position_id}  (graph {graph['graph_id']}, block {graph.get('block_number')}, as of {graph['as_of']})"]
    for layer, row in coverage["layers"].items():
        lines.append(f"\n[{row['status'].upper():>14}] {layer}")
        lines.append(f"    {row['note']}")
        for edge_id in row["edges"]:
            e = edges[edge_id]
            ev = e["evidence"]
            where = ev.get("call") or ev["method"]
            lines.append(
                f"    - {labels[e['source']]} -{e['relation']}-> {labels[e['target']]}  "
                f"({e['confidence']}; {where} @ {ev['reference']})"
            )
        for node in row.get("context_nodes", []):
            lines.append(f"    ~ context: {labels.get(node, node)}")
    gaps = [u for u in graph.get("unresolved", []) if u.get("position_id") in (None, position_id)]
    if gaps:
        lines.append("\nUnresolved:")
        lines += [f"    ? {u['subject']}: {u['reason']}" for u in gaps]
    return "\n".join(lines)
