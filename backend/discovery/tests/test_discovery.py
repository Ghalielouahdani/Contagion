"""Discovery on real recorded data (offline replay of live runs)."""

import json

import pytest

from backend.discovery.service import DiscoveryError, discover
from backend.discovery.tests.conftest import CASSETTES, EXAMPLES, FIXTURES, edges_of, load, node

LAYERS = ("settlement_chain", "yield_source_and_issuer", "oracle", "market_and_liquidity", "lending_collateral_market")
EXAMPLE_NAMES = (
    "live_ethena_01",
    "pendle_pt_holding",
    "pendle_pt_morpho_collateral",
    "morpho_susde_pyusd",
    "pendle_pt_susds",
)


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_every_example_is_complete_and_evidence_backed(replay, name):
    portfolio, graph, snapshot = replay(name)  # discover() already validated schema + consistency
    assert graph["block_number"] == snapshot["block_number"] and graph["chain_id"] == 1
    for e in graph["edges"]:
        ev = e["evidence"]
        assert ev["reference"] and ev["observed_at"].endswith("Z"), e["id"]
        if ev["method"] == "onchain_call":
            assert ev["block_number"] == graph["block_number"], e["id"]  # one block, no mixed states
    for p in portfolio["positions"]:
        layers = graph["coverage"][p["position_id"]]["layers"]
        assert set(layers) == set(LAYERS)
        assert layers["settlement_chain"]["status"] == "verified"
        assert any(e["target"] == "chain:ethereum" for e in graph["edges"])
    assert "TO_VERIFY" not in json.dumps([graph, snapshot])


def test_blueprint_portfolio_markets_are_real_and_parameterised(replay):
    _, graph, snapshot = replay("live_ethena_01")
    aave, morpho, pendle = (snapshot["markets"][k] for k in ("aave_01", "morpho_01", "pendle_01"))
    # Aave: USDe in the "USDe Stablecoin" eMode, priced by a capped USDT/USD feed (not by USDe's own market)
    assert aave["emode_category"] == 11 and aave["liquidation_threshold"] == "0.93"
    assert aave["oracle_type"] == "proxy_asset_feed" and aave["oracle_pass_through"] == "0"
    # Morpho sUSDe/USDC: exchange-rate oracle with USDe hardcoded at 1 (the fixture's hypothesis, now observed)
    assert morpho["lltv"] == "0.915" and morpho["oracle_type"] == "exchange_rate_usde_hardcoded"
    assert morpho["oracle_pass_through"] == "0" and morpho["verified"] is True
    assert pendle["maturity"] == "2026-11-26T00:00:00Z" and 0 < float(pendle["pt_implied_apy"]) < 0.2
    assert {"USDe", "USDC", "sUSDe", "PT-sUSDE-26NOV2026"} <= set(snapshot["prices_usd"])
    assert snapshot["prices_usd"]["sUSDe"]["source_type"] == "derived"
    assert snapshot["exchange_rates"]["sUSDe_USDe"]["source_type"] == "observed"


def test_aave_usde_collateral_depends_on_usdt(replay):
    """A hidden dependency only discovery reveals: Aave values USDe collateral with the USDT/USD feed."""
    _, graph, _ = replay("live_ethena_01")
    oracle = next(e["target"] for e in edges_of(graph, "market:aave_01", "prices_collateral_with"))
    feeds = [e["target"] for e in edges_of(graph, oracle, "uses_feed")]
    assert any(e["target"] == "asset:USDT" for f in feeds for e in edges_of(graph, f, "reads_price_of"))


def test_shared_exit_venue_is_one_node_with_a_quote_curve(replay):
    _, graph, snapshot = replay("live_ethena_01")
    sharing = {
        e["source"] for e in graph["edges"] if e["relation"] == "exits_via" and e["target"] == "venue:susde_usdc"
    }
    assert sharing == {"position:ethena_susde_01", "position:morpho_01"}
    venue = snapshot["exit_venues"]["venue:susde_usdc"]
    assert venue["quote_method"] == "executable_quote" and venue["fee_rate"] == "0"
    joint = venue["quotes"][-1]
    assert sorted(joint["positions"]) == ["ethena_susde_01", "morpho_01"]
    assert float(joint["loss_pct"]) >= max(float(q["loss_pct"]) for q in venue["quotes"][:-1])


def test_two_morpho_markets_give_two_different_graphs(replay):
    _, usdc_graph, usdc_snap = replay("live_ethena_01")
    _, pyusd_graph, pyusd_snap = replay("morpho_susde_pyusd")
    usdc, pyusd = usdc_snap["markets"]["morpho_01"], pyusd_snap["markets"]["morpho_pyusd_01"]
    assert usdc["details"]["market_id"] != pyusd["details"]["market_id"]
    assert (usdc["oracle_pass_through"], pyusd["oracle_pass_through"]) == ("0", "1")
    assert pyusd["oracle_type"] == "exchange_rate_x_market_feed"
    usdc_oracle = {e["target"] for e in edges_of(usdc_graph, "market:morpho_01", "prices_collateral_with")}
    pyusd_oracle = {e["target"] for e in edges_of(pyusd_graph, "market:morpho_pyusd_01", "prices_collateral_with")}
    assert usdc_oracle.isdisjoint(pyusd_oracle)


def test_pt_held_vs_pt_collateral(replay):
    """Same PT, two positions: layers 3 and 5 apply only when the PT is deposited as collateral."""
    _, held, _ = replay("pendle_pt_holding")
    _, pledged, snap = replay("pendle_pt_morpho_collateral")
    h = held["coverage"]["pt_holding_01"]["layers"]
    c = pledged["coverage"]["pt_collateral_01"]["layers"]
    assert h["oracle"]["status"] == "not_applicable" and h["lending_collateral_market"]["status"] == "not_applicable"
    assert h["lending_collateral_market"]["context_nodes"]  # the Morpho PT market, found by the collateral scan
    assert all(c[layer]["status"] not in ("not_applicable", "unresolved") for layer in LAYERS)
    market = snap["markets"]["pt_collateral_01"]
    assert market["oracle_type"].startswith("pt_linear_discount") and market["oracle_pass_through"] == "0"
    assert market["details"]["oracle_backup_pass_through"] == "1"


def test_pt_chain_reaches_ethena_through_sy_and_susde(replay):
    _, graph, _ = replay("pendle_pt_holding")
    pt = next(e["target"] for e in edges_of(graph, "position:pt_holding_01", "holds"))
    sy = edges_of(graph, pt, "redeemable_for")[0]["target"]
    yield_token = edges_of(graph, sy, "wraps")[0]["target"]
    assert node(graph, yield_token)["label"] == "sUSDe"
    assert {e["target"] for e in edges_of(graph, yield_token, "yield_generated_by")} == {"protocol:ethena"}
    assert not edges_of(graph, "protocol:pendle", "yield_generated_by")  # Pendle is not the yield source


def test_unknown_underlying_stays_unresolved(replay):
    _, graph, _ = replay("pendle_pt_susds")
    subjects = {u["subject"] for u in graph["unresolved"]}
    assert {"asset:sUSDS", "asset:USDS"} <= subjects
    layer = graph["coverage"]["pt_susds_01"]["layers"]["yield_source_and_issuer"]
    assert layer["status"] in ("inferred", "unresolved") and "not identified" in layer["note"]
    assert not any(n["id"] == "protocol:ethena" for n in graph["nodes"])


def test_committed_live_fixture_matches_its_cassette(replay):
    _, graph, snapshot = replay("live_ethena_01")
    folder = FIXTURES / "live_ethena_01"
    committed = load(folder / "dependency_graph.json")
    assert {k: v for k, v in committed.items() if k != "discovery"} == {
        k: v for k, v in graph.items() if k != "discovery"
    }
    assert load(folder / "market_snapshot.json") == snapshot


def test_fixture_mode_serves_the_contract_files():
    portfolio = load(FIXTURES / "demo_ethena_01" / "portfolio.json")
    graph, snapshot = discover(portfolio, "fixture")
    assert graph["graph_id"] == "graph_demo_01" and snapshot["snapshot_id"] == "snapshot_demo_01"
    with pytest.raises(DiscoveryError):
        discover(load(EXAMPLES / "live_ethena_01.json"), "fixture")


def test_replay_without_recording_fails_loudly():
    with pytest.raises(Exception, match="cassette"):
        discover(load(EXAMPLES / "pendle_pt_holding.json"), "replay", cassette=CASSETTES / "missing.json")
