"""Value analytics: the money numbers shown to the fund must be right and must hold up."""

import json
import time
from decimal import Decimal as D
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk.analytics import analyze
from backend.risk.analytics.derisking import Leg, exit_costs
from backend.risk.model import Snapshot
from backend.risk.tests.conftest import with_params

SCHEMAS = Path(__file__).resolve().parents[3] / "contracts" / "schemas" / "v1"


@pytest.fixture
def depeg(portfolio, snapshot, depeg_request):
    return analyze(portfolio, snapshot, depeg_request)


@pytest.fixture
def severe(portfolio, snapshot, depeg_request):
    return analyze(portfolio, snapshot, with_params(depeg_request, usde_spot_shock_pct="-0.30", oracle_lag_hours="6"))


def breaks(result, position_id, mechanism):
    row = next(r for r in result["breaking_points"]["liquidation"]
               if r["position_id"] == position_id and r["mechanism"] == mechanism)
    return None if row["immune"] else D(row["breaks_at_shock_pct"])


# --- concentration ------------------------------------------------------------

def test_four_protocols_are_one_usde_factor(depeg):
    usde = next(f for f in depeg["factor_exposure"] if f["factor"] == "usde_price")
    assert len(usde["positions_exposed"]) == 4
    assert D(usde["effective_leverage"]) == D("1.6129")  # 10.0m gross USDe exposure / 6.2m NAV


# --- breaking points ------------------------------------------------------------

def test_breaking_points_match_closed_forms(depeg):
    assert breaks(depeg, "aave_01", "usde_market_depeg") == D("-0.2941")  # 1 - 1/HF = 1 - 1.8/2.55
    assert breaks(depeg, "morpho_01", "susde_rate_cut") == D("-0.2714")  # 1 - LTV/LLTV
    assert breaks(depeg, "morpho_01", "usde_market_depeg") is None  # exchange-rate oracle
    assert breaks(depeg, "aave_01", "susde_rate_cut") is None  # USDe collateral


def test_nav_drawdown_thresholds_are_ordered(depeg):
    depegs = [D(r["usde_depeg_pct"]) for r in depeg["breaking_points"]["nav_drawdown"]]
    assert depegs == sorted(depegs, reverse=True)  # bigger drawdown needs a bigger depeg
    assert depegs[0] == D("-0.0620")  # a 6.2% depeg already costs 10% of NAV


# --- de-risking -----------------------------------------------------------------

@pytest.mark.parametrize("result_name", ["depeg", "severe"])
def test_targeted_plan_dominates_uniform(result_name, request):
    plan = request.getfixturevalue(result_name)["derisking"]
    uniform, targeted = plan["uniform"], plan["targeted"]
    assert D(targeted["loss_reduction_usd"]) >= D(uniform["loss_reduction_usd"])
    assert D(targeted["total_cost_usd"]) <= D(uniform["total_cost_usd"])
    assert D(plan["savings_usd"]) == D(uniform["total_cost_usd"]) - D(targeted["total_cost_usd"])
    assert D(plan["full_exit"]["total_cost_usd"]) > D(uniform["total_cost_usd"])


def test_shared_venue_exit_costs_more_than_separate_exits(snapshot):
    s = Snapshot.from_contract(snapshot)
    legs = [Leg("a", "venue:susde_usdc", 2e6, 1, 0), Leg("b", "venue:susde_usdc", 3e6, 1, 0)]
    together = exit_costs({"a": 1, "b": 1}, legs, s)["trading_cost_usd"]
    apart = exit_costs({"a": 1}, legs, s)["trading_cost_usd"] + exit_costs({"b": 1}, legs, s)["trading_cost_usd"]
    assert together > apart


def test_break_even_probability_is_cost_over_protection(depeg):
    t = depeg["derisking"]["targeted"]
    expected = D(t["total_cost_usd"]) / D(t["loss_reduction_usd"])
    assert abs(D(t["break_even_probability"]) - expected) < D("0.0001")


# --- liquidation protection ------------------------------------------------------------

def test_no_liquidation_no_protection_value(depeg):
    assert depeg["liquidation_protection"] == []
    assert D(depeg["headline"]["liquidation_protection_net_benefit_usd"]) == 0


def test_preemptive_deleverage_restores_safety_target(severe):
    row = next(r for r in severe["liquidation_protection"] if r["position_id"] == "aave_01")
    assert D(row["liquidation_penalty_usd"]) == D("45000.00")
    y = float(row["preemptive"]["deleverage_usd"])
    hf_after_shock = (3_000_000 - y) * 0.70 * 0.85 / (1_800_000 - y)
    assert hf_after_shock == pytest.approx(1.05, abs=1e-6)
    pre = row["preemptive"]
    assert D(pre["net_benefit_usd"]) == D(pre["penalty_avoided_usd"]) - D(pre["cost_usd"])
    assert D(pre["net_benefit_usd"]) > 0


def test_oracle_lag_window_is_priced(severe):
    lag = severe["liquidation_protection"][0]["during_oracle_lag"]
    assert D(lag["window_hours"]) == 6
    y = float(lag["deleverage_usd"])
    assert (2_100_000 - y) * 0.85 / (1_800_000 - y) == pytest.approx(1.05, abs=1e-6)


# --- contract & speed ------------------------------------------------------------

def test_analytics_validates_against_schema(depeg, severe):
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((SCHEMAS / "risk_analytics.schema.json").read_text()), registry=registry)
    for result in (depeg, severe):
        errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(result)]
        assert not errors, errors


def test_fast_enough_for_live_sliders(portfolio, snapshot, depeg_request):
    start = time.perf_counter()
    for _ in range(5):
        analyze(portfolio, snapshot, depeg_request)
    assert (time.perf_counter() - start) / 5 < 0.25
