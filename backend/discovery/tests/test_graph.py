import pytest

from backend.discovery.coverage import position_coverage
from backend.discovery.graph import Evidence, GraphBuilder

EV = Evidence("onchain_call", "0xabc", "2026-10-10T00:00:00Z", "verified")


def test_same_symbol_different_address_gets_two_nodes():
    g = GraphBuilder()
    a = g.allocate_id("asset", "USDe", 1, "0x" + "1" * 40)
    g.node(a, "asset", "USDe")
    g.bind_address(a, 1, "0x" + "1" * 40)
    b = g.allocate_id("asset", "USDe", 1, "0x" + "2" * 40)
    assert a == "asset:USDe" and b == "asset:USDe.22222222"
    assert g.allocate_id("asset", "anything", 1, "0x" + "1" * 40) == a  # same address -> same node


def test_node_merge_reports_conflicts_instead_of_overwriting():
    g = GraphBuilder()
    g.node("asset:X", "asset", "X", decimals=18)
    g.node("asset:X", "asset", "X", decimals=6, name="x")
    assert g.nodes["asset:X"].attributes == {"decimals": 18, "name": "x"}
    assert any("decimals" in c for c in g.conflicts)


def test_edges_dedupe_and_keep_the_strongest_confidence():
    g = GraphBuilder()
    g.node("asset:A", "asset", "A")
    g.node("asset:B", "asset", "B")
    g.edge("asset:A", "asset:B", "redeemable_for", "exchange_rate", EV, "inferred")
    g.edge("asset:A", "asset:B", "redeemable_for", "exchange_rate", EV, "verified")
    g.edge("asset:A", "asset:B", "redeemable_for", "exchange_rate", EV, "assumed")
    assert len(g.edges) == 1
    assert next(iter(g.edges.values())).confidence == "verified"


def test_edge_to_unknown_node_is_refused():
    g = GraphBuilder()
    g.node("asset:A", "asset", "A")
    with pytest.raises(KeyError):
        g.edge("asset:A", "asset:missing", "issued_by", "issuer_backing", EV, "verified")


def test_edge_ids_are_stable_content_hashes():
    g1, g2 = GraphBuilder(), GraphBuilder()
    for g in (g1, g2):
        g.node("asset:A", "asset", "A")
        g.node("protocol:p", "protocol", "P")
    e1 = g1.edge("asset:A", "protocol:p", "issued_by", "issuer_backing", EV, "verified")
    e2 = g2.edge("asset:A", "protocol:p", "issued_by", "issuer_backing", EV, "documented")
    assert e1.id == e2.id and e1.id.startswith("edge:issued_by.")


def test_reachable_edges_terminate_on_cycles():
    g = GraphBuilder()
    for n in "ABC":
        g.node(f"asset:{n}", "asset", n)
    g.edge("asset:A", "asset:B", "wraps", "exchange_rate", EV, "verified")
    g.edge("asset:B", "asset:C", "wraps", "exchange_rate", EV, "verified")
    g.edge("asset:C", "asset:A", "wraps", "exchange_rate", EV, "verified")
    assert len(g.reachable_edges("asset:A")) == 3


def _holding_graph():
    g = GraphBuilder()
    g.node("position:p1", "position", "holding")
    g.node("asset:T", "asset", "T")
    g.node("chain:ethereum", "chain", "Ethereum")
    g.edge("position:p1", "asset:T", "holds", "mark_to_market", EV, "verified")
    g.edge("asset:T", "chain:ethereum", "deployed_on", "settlement", EV, "verified")
    return g


def test_coverage_marks_missing_layers_explicitly():
    g = _holding_graph()
    unresolved = [{"subject": "asset:T", "reason": "issuer unknown", "layer": "yield_source_and_issuer"}]
    layers = position_coverage(g, {"position_id": "p1", "position_type": "token_holding"}, unresolved)["layers"]
    assert layers["settlement_chain"]["status"] == "verified"
    assert layers["yield_source_and_issuer"]["status"] == "unresolved"
    assert "issuer unknown" in layers["yield_source_and_issuer"]["note"]
    assert layers["oracle"]["status"] == "not_applicable"
    assert layers["lending_collateral_market"]["status"] == "not_applicable"
    assert layers["market_and_liquidity"]["status"] == "unresolved"


def test_coverage_lists_context_markets_without_making_them_dependencies():
    g = _holding_graph()
    g.node("market:ctx", "market", "lending market accepting T")
    g.edge("market:ctx", "asset:T", "collateral_asset", "mark_to_market", EV, "verified")
    layers = position_coverage(g, {"position_id": "p1", "position_type": "token_holding"}, [])["layers"]
    assert layers["lending_collateral_market"]["status"] == "not_applicable"
    assert layers["lending_collateral_market"]["context_nodes"] == ["market:ctx"]
