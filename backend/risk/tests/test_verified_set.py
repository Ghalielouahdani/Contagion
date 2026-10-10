"""Engine on the fixture set built from on-chain verified markets (contracts/fixtures/verified_2026_10_10)."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.risk import simulate
from backend.risk.analytics import analyze
from backend.risk.tests.test_golden import assert_same

SET = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "verified_2026_10_10"


def load(name):
    return json.loads((SET / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def inputs():
    return load("portfolio"), load("market_snapshot"), load("dependency_graph")


@pytest.mark.parametrize("request_name, stored", [
    ("scenario_request", "risk_result"),
    ("scenario_request_liquidity", "risk_result_liquidity"),
])
def test_reproduces_stored_risk_results(inputs, request_name, stored):
    p, s, g = inputs
    assert_same(simulate(p, s, load(request_name), g), load(stored))


@pytest.mark.parametrize("request_name, stored", [
    ("scenario_request", "risk_analytics"),
    ("scenario_request_severe", "risk_analytics_severe"),
])
def test_reproduces_stored_analytics(inputs, request_name, stored):
    p, s, _ = inputs
    assert_same(analyze(p, s, load(request_name)), load(stored))


def test_nav_matches_portfolio_totals(inputs):
    p, s, g = inputs
    result = simulate(p, s, load("scenario_request"), g)
    assert D(result["portfolio"]["net_equity_before_usd"]) == D(p["totals"]["net_equity_usd"])


def test_every_path_is_backed_by_verified_or_documented_evidence(inputs):
    p, s, g = inputs
    for position in simulate(p, s, load("scenario_request"), g)["positions"]:
        contagion = position["contagion"]
        assert contagion["graph_gaps"] == [] and contagion["unmodeled_exposures"] == []
        assert contagion["evidence_confidence"] in ("verified", "documented"), position["position_id"]


def test_real_oracles_flip_the_demo_story(inputs):
    # Aave prices USDe with Chainlink USDT/USD: immune to a USDe depeg.
    # Morpho sUSDe/PYUSD reads Chainlink USDe/USD: liquidated at a 27.2% depeg.
    p, s, _ = inputs
    points = {(r["position_id"], r["mechanism"]): r for r in analyze(p, s, load("scenario_request"))["breaking_points"]["liquidation"]}
    assert points[("aave_01", "usde_market_depeg")]["immune"] is True
    assert D(points[("morpho_01", "usde_market_depeg")]["breaks_at_shock_pct"]) == D("-0.2724")  # 1 - LTV/LLTV with LTV = 2.000134m / 3.004416m
