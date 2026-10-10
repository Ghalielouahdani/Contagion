"""Liquidation cascade (backend/risk/cascade.py) on contracts/fixtures/demo_lending_01.

Markets: USDe/USDC with a market-price oracle (pass-through 1) and sUSDe/USDC with an exchange-rate
oracle (pass-through 0); 100M debt each in LTV buckets 0.50/0.70/0.80/0.86/0.90 (15/25/25/20/15M);
LLTV 0.915, LIF 1.026; collateral venues: USDe 300M and sUSDe 200M proxy depth.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.risk import cascade, simulate
from backend.risk.analytics import analyze
from backend.risk.model import Portfolio, Snapshot
from backend.risk.tests.conftest import by_id, with_params
from backend.risk.tests.test_golden import assert_same

SET = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "demo_lending_01"


def load(name: str) -> dict:
    return json.loads((SET / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def models():
    return Portfolio.from_contract(load("portfolio")), Snapshot.from_contract(load("market_snapshot"))


def run(models, shock=-0.05, depth=0.5, **kw):
    portfolio, snapshot = models
    return cascade.run(portfolio, snapshot, {"USDe": shock, "sUSDe": shock}, depth, **kw)


def test_reproduces_golden():
    result = simulate(load("portfolio"), load("market_snapshot"), load("scenario_request_cascade"), load("dependency_graph"))
    assert_same(result, load("risk_result_cascade"))


def test_first_round_by_hand(models):
    # -5%: bucket 0.90 -> LTV 0.947 > 0.915: 15M liquidated, 15M x 1.026 = 15.39M USDe sold into 300M x 50% depth.
    # Marginal discount 1 - (150 / 165.39)^2 = 17.75% -> USDe 0.95 x (1 - 0.1775) - 1 = -21.86%.
    first = run(models).rounds[0]
    assert first["liquidated_debt_usd"] == pytest.approx(15e6)
    assert first["collateral_sold_usd"] == pytest.approx(15.39e6)
    assert first["moves"]["USDe"] == pytest.approx(0.95 * (150 / 165.39) ** 2 - 1, rel=1e-4)


def test_lender_bad_debt_appears_only_with_the_cascade():
    request = load("scenario_request_cascade")
    result = simulate(load("portfolio"), load("market_snapshot"), request)
    assert Decimal(result["comparison"]["runs"][0]["total_conditional_loss_usd"]) == 0  # -5% alone: no lender loss
    # Market bad debt 9.054M; our supply share 5 / 120.
    assert Decimal(by_id(result)["lend_usde_01"]["loss_components"]["bad_debt"]) == Decimal("377264.65")


def test_exchange_rate_oracle_is_a_circuit_breaker(models):
    result = run(models)
    assert result.moves["sUSDe"] == pytest.approx(-0.05)  # nothing liquidated, nothing sold
    assert sum(b.liquidated for b in result.buckets if b.asset == "sUSDe") == 0


def test_converges_and_liquidates_each_bucket_once(models):
    for shock in (-0.02, -0.05, -0.2, -0.5):
        result = run(models, shock, depth=0.2)
        assert result.converged
        assert len(result.rounds) <= len(result.buckets) + 1
        assert all(b.liquidated <= b.debt + 1e-6 for b in result.buckets)


def test_no_shock_no_cascade(models):
    result = run(models, shock=0.0)
    assert result.moves == {"USDe": 0.0, "sUSDe": 0.0} and len(result.rounds) == 1


def test_arbitrage_absorption_dampens_the_cascade(models):
    finals = [run(models, absorption=a).moves["USDe"] for a in (0.0, 0.5, 0.8, 0.95)]
    assert finals == sorted(finals)  # more absorption, less negative final price
    assert finals[0] < -0.5 < -0.1 < finals[-1]  # the assumption spans "crash" to "blip"


def test_less_depth_bigger_cascade(models):
    finals = [run(models, depth=k).moves["USDe"] for k in (1.0, 0.5, 0.2)]
    assert finals == sorted(finals, reverse=True)


def test_impact_aware_liquidators_bound_the_spiral_by_the_incentive(models):
    # Liquidators stop when their own selling's marginal discount reaches 1 - 1/LIF = 2.53%.
    result = run(models, impact_aware=True)
    assert result.moves["USDe"] >= 0.95 / 1.026 - 1 - 1e-6
    assert result.moves["USDe"] < -0.05


def test_missing_venue_is_flagged(models):
    portfolio, snapshot = models
    from dataclasses import replace
    bare = replace(snapshot, venues={})
    result = cascade.run(portfolio, bare, {"USDe": -0.05, "sUSDe": -0.05}, 0.5)
    assert result.moves["USDe"] == -0.05
    assert any("No exit venue for USDe" in w for w in result.warnings)


def test_borrow_positions_feed_the_cascade_without_market_data():
    # demo_ethena_01 has no borrower buckets: our own Aave/Morpho borrows are the only borrowers.
    fixtures = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "demo_ethena_01"
    read = lambda n: json.loads((fixtures / f"{n}.json").read_text())
    request = with_params(load("scenario_request_cascade"), usde_spot_shock_pct=-0.30)
    request.update(portfolio_id="demo_ethena_01", snapshot_id="snapshot_demo_01", graph_id="graph_demo_01")
    result = simulate(read("portfolio"), read("market_snapshot"), request)
    # -30%: Aave (HF 0.99) is liquidated; its USDe hits the venue and deepens the move.
    assert Decimal(result["cascade"]["final_moves"]["USDe"]) <= Decimal("-0.30")
    assert Decimal(result["cascade"]["liquidated_debt_usd"]) > 0


def test_lender_cascade_loss_is_driven_by_oracle_and_depth():
    # Bad debt is fixed when a bucket is liquidated, so for a lender the oracle (does the market see the
    # cascade?) and the venue depth (how far each round pushes the price) dominate; arbitrage absorption
    # mostly moves the final price, i.e. holders' mark losses.
    rows = analyze(load("portfolio"), load("market_snapshot"), load("scenario_request_cascade"))["sensitivity"]["tornado"]
    assert [r["assumption"] for r in rows[:2]] == ["Oracle pass-through (all markets)", "venue:usde_usdc depth"]
    assert any(r["assumption"] == "Arbitrage absorption between rounds" and float(r["swing_usd"]) > 0 for r in rows)
