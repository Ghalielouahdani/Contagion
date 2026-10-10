"""Lender positions (lending_supply) on contracts/fixtures/demo_lending_01.

Two fictional Morpho markets, identical except for the oracle: USDe at its market price
(pass-through 1) and sUSDe through an exchange rate with USDe at 1 USD (pass-through 0).
Each: 120M USDC supplied, 100M borrowed, we supply 5M (share 1/24), LLTV 0.915, LIF 1.026.
Borrower debt by oracle LTV: 0.50: 15M, 0.70: 25M, 0.80: 25M, 0.86: 20M, 0.90: 15M.
"""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk import simulate
from backend.risk.analytics import analyze
from backend.risk.lending import LenderShock, shock
from backend.risk.model import Position
from backend.risk.tests.conftest import by_id, with_params
from backend.risk.tests.test_golden import SCHEMAS, assert_same

SET = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "demo_lending_01"
REQUESTS = ["", "_liquidity", "_carry"]


def load(name: str) -> dict:
    return json.loads((SET / f"{name}.json").read_text())


def run(request: dict, graph=None) -> dict:
    return simulate(load("portfolio"), load("market_snapshot"), request, graph)


def loss(result: dict, position_id: str) -> Decimal:
    return Decimal(by_id(result)[position_id]["conditional_loss_usd"])


@pytest.mark.parametrize("suffix", REQUESTS)
def test_reproduces_golden(suffix):
    assert_same(run(load(f"scenario_request{suffix}"), load("dependency_graph")), load(f"risk_result{suffix}"))


def test_every_file_validates_against_its_schema():
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    manifest = load("manifest")
    for entry in manifest["files"].values():
        schema = json.loads((SET / entry["schema"]).resolve().read_text())
        document = json.loads((SET / entry["path"]).read_text())
        errors = [e.message for e in Draft202012Validator(schema, registry=registry).iter_errors(document)]
        assert not errors, (entry["path"], errors)


def test_market_price_oracle_realises_bad_debt():
    # -20%: buckets 0.80 / 0.86 / 0.90 go to oracle LTV 1.0 / 1.075 / 1.125 > 0.915 (60% of debt).
    # Liquidators repay collateral / 1.026: bad debt 0.634M + 1.867M + 2.005M = 4.505M; our 1/24 = 187,703.68.
    result = by_id(run(load("scenario_request")))["lend_usde_01"]
    assert Decimal(result["loss_components"]["bad_debt"]) == Decimal("187703.68")
    assert Decimal(result["loss_components"]["undercollateralized_debt"]) == 0


def test_exchange_rate_oracle_hides_the_loss_from_the_protocol():
    # Same move, oracle blind: nothing is liquidatable, but at market prices buckets 0.86 and 0.90 are
    # underwater by 1.395M + 1.667M = 3.062M; our 1/24 = 127,583.98, not yet realised.
    result = by_id(run(load("scenario_request")))["lend_susde_01"]
    assert Decimal(result["loss_components"]["bad_debt"]) == 0
    assert Decimal(result["loss_components"]["undercollateralized_debt"]) == Decimal("127583.98")
    assert any("invisible to the oracle" in w for w in result["warnings"])


def test_no_shock_no_lender_loss():
    result = run(with_params(load("scenario_request"), usde_spot_shock_pct=0))
    assert all(Decimal(p["conditional_loss_usd"]) == 0 for p in result["positions"])


def test_lender_loss_monotonic_and_zero_for_small_shocks():
    losses = [loss(run(with_params(load("scenario_request"), usde_spot_shock_pct=-s)), "lend_usde_01")
              for s in (0.0, 0.01, 0.05, 0.10, 0.20, 0.40, 0.80)]
    assert losses == sorted(losses)
    # Bucket 0.90 is liquidatable past -1.6% (LTV > 0.915), but liquidators still repay in full until
    # collateral / LIF < debt, i.e. past -7.7%: no lender loss at -1% or -5%.
    assert losses[1] == losses[2] == 0


def test_lender_loss_is_capped_by_its_supply():
    result = run(with_params(load("scenario_request"), usde_spot_shock_pct=-0.99))
    assert loss(result, "lend_usde_01") <= Decimal("5000000.00")


def test_oracle_switch_realises_the_hidden_loss():
    # governance_change: the sUSDe market switches to a market-price oracle before the depeg.
    request = load("scenario_request")
    params = {k: v for k, v in request["scenario"]["parameters"].items() if k != "oracle_pass_through_override"}
    request["scenario"] = {"scenario_id": "governance_change", "horizon_days": 7, "parameters": {
        **params, "liquidation_threshold_shift": "0", "oracle_switch_pass_through": "1.0", "target_markets": ["lend_susde_01"]}}
    result = by_id(run(request))["lend_susde_01"]
    assert Decimal(result["loss_components"]["bad_debt"]) > 0
    assert Decimal(result["loss_components"]["undercollateralized_debt"]) == 0


def test_backing_failure_reaches_lenders_through_borrowers():
    request = load("scenario_request")
    request["scenario"] = {"scenario_id": "node_shock", "horizon_days": 7, "parameters": {
        "node_id": "offchain:ethena_backing", "loss_pct": "0.20", "oracle_pass_through_override": None}}
    result = run(request, load("dependency_graph"))
    assert loss(result, "lend_usde_01") > 0 and loss(result, "lend_susde_01") > 0
    assert all(p["contagion"]["graph_gaps"] == [] for p in result["positions"])


def test_liquidity_crisis_locks_without_loss():
    result = run(load("scenario_request_liquidity"))
    assert Decimal(result["portfolio"]["total_conditional_loss_usd"]) == 0
    for p in result["positions"]:
        assert any("1,000,000 stays locked" in w for w in p["warnings"])  # idle 20M x 20% = 4M withdrawable


def test_lender_earns_the_squeeze():
    # Supply APY = 60% borrow x 100/120 utilization = 50%; 5M x 50% x 30/365 = 205,479.45 gained.
    result = run(load("scenario_request_carry"))
    assert loss(result, "lend_usde_01") == Decimal("-205479.45")


def test_missing_borrower_distribution_is_flagged():
    snapshot = copy.deepcopy(load("market_snapshot"))
    del snapshot["markets"]["lend_usde_01"]["borrower_ltv_buckets"]
    result = simulate(load("portfolio"), snapshot, load("scenario_request"))
    assert by_id(result)["lend_usde_01"]["calculation_status"] == "insufficient_data"
    assert result["portfolio"]["aggregation_status"] == "insufficient_data"


def test_shock_function_matches_the_formula():
    position = Position("p", "morpho", "lending_supply", "venue:x", 1.0, 0.0, 1.0, "fictional",
                        asset_symbol="USDC", quantity=10.0)
    market = {"lltv": "0.9", "liquidation_incentive": "0.05", "total_supply_assets": "100",
              "total_borrow_assets": "80", "borrower_ltv_buckets": [{"ltv": "0.8", "debt_share": "1"}]}
    # C0 = 100; -20% -> C = 80 -> LTV 1.0 > 0.9: repaid 80 / 1.05 = 76.19, bad debt 3.81.
    assert shock(position, market, -0.20, 1.0) == pytest.approx(
        LenderShock(0.1, 80 - 80 / 1.05, 0.0, 80.0, 80.0))


@pytest.mark.parametrize("suffix", REQUESTS)
def test_analytics_run_on_lenders(suffix):
    result = analyze(load("portfolio"), load("market_snapshot"), load(f"scenario_request{suffix}"))
    assert result["headline"]["nav_usd"] == "10000000.00"


def test_lender_threshold_exposure_is_not_flagged_unmodeled():
    # Backing -10% on the exchange-rate market: collateral still covers every bucket (l <= 0.90), so no loss,
    # but the exposure is modeled: a note, not an "exposure not modeled" flag.
    request = load("scenario_request")
    request["scenario"] = {"scenario_id": "node_shock", "horizon_days": 7, "parameters": {
        "node_id": "offchain:ethena_backing", "loss_pct": "0.10", "oracle_pass_through_override": None}}
    for name, req in (("node_shock", request), ("carry", load("scenario_request_carry"))):
        result = by_id(run(req, load("dependency_graph")))["lend_susde_01"]
        assert result["contagion"]["unmodeled_exposures"] == [], name
        assert Decimal(result["loss_components"]["bad_debt"]) == 0, name


def test_carry_lender_sees_borrowers_drift():
    # Borrow 60% for 300 days: debt x1.493, sUSDe collateral flat at 0% APY -> buckets 0.80/0.86/0.90 go to
    # LTV 1.19/1.28/1.34 > 0.915, and collateral / LIF no longer covers their debt: the lender takes bad debt.
    request = load("scenario_request_carry")
    request["scenario"]["horizon_days"] = 300
    result = by_id(run(request))["lend_susde_01"]
    assert Decimal(result["loss_components"]["bad_debt"]) > 0
    # A rising sUSDe rate offsets part of the drift.
    request = with_params(request, susde_apy=0.30)
    assert Decimal(by_id(run(request))["lend_susde_01"]["loss_components"]["bad_debt"]) < Decimal(result["loss_components"]["bad_debt"])
