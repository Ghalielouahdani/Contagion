"""Dependency graph view for the risk engine.

Edge direction follows the contract: source depends on target (position -> market ->
asset -> backing). A shock on a node reaches every node that can walk forward to it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

CONFIDENCE_RANK = {"assumed": 0, "inferred": 1, "documented": 2, "verified": 3}


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    relation: str
    risk_channel: str
    confidence: str
    evidence_status: str


class Graph:
    def __init__(self, graph_id: str, nodes: dict[str, dict], edges: list[Edge]):
        self.graph_id = graph_id
        self.nodes = nodes
        self.edges = edges
        self.out: dict[str, list[Edge]] = defaultdict(list)
        for edge in edges:
            self.out[edge.source].append(edge)

    @classmethod
    def from_contract(cls, raw: dict) -> Graph:
        return cls(
            raw["graph_id"],
            {n["id"]: n for n in raw["nodes"]},
            [Edge(e["id"], e["source"], e["target"], e["relation"], e["risk_channel"], e["confidence"], e["evidence"]["status"])
             for e in raw["edges"]],
        )

    def has(self, node_id: str) -> bool:
        return node_id in self.nodes

    def label(self, node_id: str) -> str:
        return self.nodes.get(node_id, {}).get("label", node_id)

    def reachable(self, start: str) -> set[str]:
        """Every node start depends on, directly or transitively."""
        seen, queue = {start}, deque([start])
        while queue:
            for edge in self.out[queue.popleft()]:
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        seen.discard(start)
        return seen

    def paths(self, start: str, goal: str, max_depth: int = 6, limit: int = 3) -> list[list[Edge]]:
        """Shortest simple dependency paths from start to goal (at most `limit`)."""
        found: list[list[Edge]] = []
        queue: deque[tuple[str, list[Edge]]] = deque([(start, [])])
        while queue and len(found) < limit:
            node, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            visited = {start, *(e.target for e in path)}
            for edge in self.out[node]:
                if edge.target in visited:
                    continue
                if edge.target == goal:
                    found.append(path + [edge])
                    if len(found) >= limit:
                        break
                else:
                    queue.append((edge.target, path + [edge]))
        return found

    def exits_of(self, node_id: str) -> list[str]:
        return [e.target for e in self.out[node_id] if e.relation == "exits_via"]


def path_confidence(path: list[Edge]) -> str:
    return min((e.confidence for e in path), key=CONFIDENCE_RANK.__getitem__)
