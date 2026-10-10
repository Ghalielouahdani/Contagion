"""Evidence-backed dependency graph under construction.

Convention (same as the contract and the risk engine): an edge source -> target means
"source depends on target": a problem at the target can reach the source.

Identity rules:
- a contract is identified by (chain_id, address), never by its symbol: two tokens with the
  same symbol get two nodes, and the second id gets an address suffix;
- node ids stay readable (asset:USDe, market:pendle_01) because the risk engine and the
  frontend key on them; the address lives in attributes.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

CONFIDENCE_RANK = {"assumed": 0, "inferred": 1, "documented": 2, "verified": 3}
_ID_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(text: str) -> str:
    return _ID_SAFE.sub("-", text).strip("-") or "unnamed"


def weakest(confidences) -> str:
    return min(confidences, key=CONFIDENCE_RANK.__getitem__)


def strongest(confidences) -> str:
    return max(confidences, key=CONFIDENCE_RANK.__getitem__)


@dataclass
class Evidence:
    method: str  # onchain_call | protocol_api | protocol_documentation | third_party_api | fixture
    reference: str  # contract address, API URL or document URL
    observed_at: str
    status: str  # verified | to_verify | assumed | documented
    block_number: int | None = None
    call: str | None = None
    note: str | None = None

    def to_contract(self) -> dict:
        out = {
            "method": self.method,
            "reference": self.reference,
            "observed_at": self.observed_at,
            "status": self.status,
        }
        if self.block_number is not None:
            out["block_number"] = self.block_number
        if self.call:
            out["call"] = self.call
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Node:
    id: str
    type: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_contract(self) -> dict:
        out = {"id": self.id, "type": self.type, "label": self.label}
        if self.attributes:
            out["attributes"] = self.attributes
        return out


@dataclass
class Edge:
    source: str
    target: str
    relation: str
    risk_channel: str
    evidence: Evidence
    confidence: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.source, self.relation, self.target

    @property
    def id(self) -> str:
        digest = hashlib.sha1("|".join(self.key).encode()).hexdigest()[:10]
        return f"edge:{self.relation}.{digest}"

    def to_contract(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "risk_channel": self.risk_channel,
            "evidence": self.evidence.to_contract(),
            "confidence": self.confidence,
        }


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}
        self.conflicts: list[str] = []
        self._by_address: dict[tuple[int, str], str] = {}

    # nodes -------------------------------------------------------------------------------
    def node(self, node_id: str, node_type: str, label: str, **attributes: Any) -> str:
        """Create a node, or merge attributes into the existing one (conflicts are reported, not overwritten)."""
        existing = self.nodes.get(node_id)
        if existing is None:
            self.nodes[node_id] = Node(
                node_id, node_type, label, {k: v for k, v in attributes.items() if v is not None}
            )
            return node_id
        if existing.type != node_type:
            self.conflicts.append(f"{node_id}: type {existing.type!r} vs {node_type!r}")
        for key, value in attributes.items():
            if value is None:
                continue
            if key in existing.attributes and existing.attributes[key] != value:
                if isinstance(value, dict) and isinstance(existing.attributes[key], dict):
                    existing.attributes[key] = {**existing.attributes[key], **value}
                    continue
                self.conflicts.append(f"{node_id}.{key}: {existing.attributes[key]!r} vs {value!r}")
                continue
            existing.attributes[key] = value
        return node_id

    def node_for_address(self, chain_id: int, address: str) -> str | None:
        return self._by_address.get((chain_id, address.lower()))

    def bind_address(self, node_id: str, chain_id: int, address: str) -> None:
        key = (chain_id, address.lower())
        bound = self._by_address.get(key)
        if bound is not None and bound != node_id:
            self.conflicts.append(f"address {address} bound to both {bound} and {node_id}")
            return
        self._by_address[key] = node_id

    def allocate_id(self, prefix: str, name: str, chain_id: int, address: str) -> str:
        """Readable id for an on-chain object; an address suffix disambiguates name collisions."""
        bound = self.node_for_address(chain_id, address)
        if bound:
            return bound
        candidate = f"{prefix}:{safe_name(name)}"
        if candidate in self.nodes:
            candidate = f"{candidate}.{address.lower()[2:10]}"
        return candidate

    # edges -------------------------------------------------------------------------------
    def edge(
        self, source: str, target: str, relation: str, risk_channel: str, evidence: Evidence, confidence: str
    ) -> Edge:
        for end in (source, target):
            if end not in self.nodes:
                raise KeyError(f"edge {source} -[{relation}]-> {target}: unknown node {end}")
        new = Edge(source, target, relation, risk_channel, evidence, confidence)
        old = self.edges.get(new.key)
        if old is None or CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[old.confidence]:
            self.edges[new.key] = new
            return new
        return old

    def out_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges.values() if e.source == node_id]

    def in_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges.values() if e.target == node_id]

    def reachable_edges(self, start: str, max_depth: int = 12) -> list[Edge]:
        """Every edge on some dependency path from start (cycle-safe, depth-bounded)."""
        out: dict[str, list[Edge]] = {}
        for e in self.edges.values():
            out.setdefault(e.source, []).append(e)
        seen_nodes, seen_edges = {start}, []
        queue = deque([(start, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for e in out.get(node, []):
                seen_edges.append(e)
                if e.target not in seen_nodes:
                    seen_nodes.add(e.target)
                    queue.append((e.target, depth + 1))
        return seen_edges

    # export ------------------------------------------------------------------------------
    def to_contract(self) -> tuple[list[dict], list[dict]]:
        nodes = [n.to_contract() for n in sorted(self.nodes.values(), key=lambda n: n.id)]
        edges = [e.to_contract() for e in sorted(self.edges.values(), key=lambda e: (e.source, e.relation, e.target))]
        return nodes, edges
