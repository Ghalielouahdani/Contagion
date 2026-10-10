"""Five dependency layers per position, computed from the discovered graph.

The challenge's Pendle PT example names five layers. Each position gets, per layer, the
nodes and edges found on its dependency paths, a status (the weakest confidence among the
layer's defining edges, or unresolved / not_applicable) and a one-line explanation.
Components found off the position's own paths (e.g. lending markets that accept a held PT)
are listed as context, not as dependencies.
"""

from __future__ import annotations

from backend.discovery.graph import Edge, GraphBuilder, weakest

LAYERS = ("settlement_chain", "yield_source_and_issuer", "oracle", "market_and_liquidity", "lending_collateral_market")

# relations that make up each layer, and the subset whose confidence sets the layer status
MEMBERS = {
    "settlement_chain": {"deployed_on"},
    "yield_source_and_issuer": {"issued_by", "yield_generated_by", "backed_by", "wraps", "redeemable_for"},
    "oracle": {"prices_collateral_with", "prices_debt_with", "uses_feed", "reads_price_of"},
    "market_and_liquidity": {"position_in", "exits_via", "routes_through", "pools_asset", "part_of_protocol"},
    "lending_collateral_market": {"collateral_asset", "debt_asset"},
}
DEFINING = {
    "settlement_chain": {"deployed_on"},
    "yield_source_and_issuer": {"issued_by", "yield_generated_by", "backed_by"},
    "oracle": {"prices_collateral_with", "prices_debt_with"},
    "market_and_liquidity": {"position_in", "pools_asset", "routes_through"},
    "lending_collateral_market": {"collateral_asset", "debt_asset"},
}


def position_coverage(g: GraphBuilder, position: dict, unresolved: list[dict]) -> dict:
    node = f"position:{position['position_id']}"
    closure = g.reachable_edges(node)
    closure_nodes = {node} | {e.target for e in closure}
    open_items = [u for u in unresolved if u["subject"] in closure_nodes]
    layers = {}
    for layer in LAYERS:
        members = [e for e in closure if e.relation in MEMBERS[layer] and _belongs(g, layer, e)]
        defining = [e for e in members if e.relation in DEFINING[layer]]
        layers[layer] = _layer(
            g, layer, position, members, defining, closure_nodes, [u for u in open_items if u.get("layer") == layer]
        )
    return {"layers": layers}


def _layer(
    g: GraphBuilder,
    layer: str,
    position: dict,
    members: list[Edge],
    defining: list[Edge],
    closure_nodes: set[str],
    open_items: list[dict],
) -> dict:
    nodes = sorted({e.target for e in members})
    edges = sorted(e.id for e in members)
    is_borrow = position["position_type"] == "collateralized_borrow"

    if layer == "oracle" and not defining:
        context = _context(g, closure_nodes, {"reads_price_of"}, "oracle")
        note = (
            "no oracle on this position's valuation path: a holding is marked to market and sold, not "
            "liquidated against an oracle"
        )
        if context:
            note += f"; oracles pricing its assets elsewhere: {', '.join(context)}"
        return _row("not_applicable", [], [], note, context)
    if layer == "lending_collateral_market" and not is_borrow:
        context = _context(g, closure_nodes, {"collateral_asset"}, "market")
        note = "position is not deposited as collateral"
        if context:
            note += (
                "; lending markets using an asset of its dependency path as collateral (context only): "
                + ", ".join(context)
            )
        return _row("not_applicable", [], [], note, context)
    if not defining:
        reason = "; ".join(u["reason"] for u in open_items) or "no edge of this layer was discovered"
        return _row("unresolved", nodes, edges, reason)

    status = weakest(e.confidence for e in defining)
    if open_items and status in ("verified", "documented"):
        status = "inferred"
    note = "; ".join(_describe(g, e) for e in sorted(defining, key=lambda e: (e.relation, e.source)))
    if open_items:
        note += " | open: " + "; ".join(u["reason"] for u in open_items)
    return _row(status, nodes, edges, note)


def _belongs(g: GraphBuilder, layer: str, e: Edge) -> bool:
    """part_of_protocol counts for the market layer only when a market or venue is the member."""
    return e.relation != "part_of_protocol" or g.nodes[e.source].type in ("market", "venue")


def _row(status: str, nodes: list[str], edges: list[str], note: str, context: list[str] | None = None) -> dict:
    row = {"status": status, "nodes": nodes, "edges": edges, "note": note}
    if context:
        row["context_nodes"] = context
    return row


def _context(g: GraphBuilder, closure_nodes: set[str], relations: set[str], node_type: str) -> list[str]:
    """Nodes outside the closure that point INTO it with one of the relations."""
    return sorted(
        {
            e.source
            for e in g.edges.values()
            if e.relation in relations
            and e.target in closure_nodes
            and e.source not in closure_nodes
            and g.nodes[e.source].type == node_type
        }
    )


def _describe(g: GraphBuilder, e: Edge) -> str:
    return f"{g.nodes[e.source].label} -{e.relation}-> {g.nodes[e.target].label} [{e.confidence}]"
