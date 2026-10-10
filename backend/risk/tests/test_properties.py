"""Financial properties the engine must satisfy for any inputs, not just the fixtures."""

import copy
from decimal import Decimal as D

import pytest

from backend.risk import simulate
from backend.risk.liquidity import haircut
from backend.risk.metrics import health_factor, hf_distance_to_liquidation, ltv, ltv_distance_to_liquidation
from backend.risk.pricing import pt_price
from backend.risk.tests.conftest import by_id, with_params


def depeg(portfolio, snapshot, request, **params):
    return simulate(portfolio, snapshot, with_params(request, **params))


# --- formulas ---------------------------------------------------------------

def test_metric_formulas():
    assert health_factor(3_000_000, 0.85, 1_800_000) == pytest.approx(1.416667, rel=1e-6)
    assert hf_distance_to_liquidation(1.0) == 0
    assert ltv(2_000_000, 3_000_000) == pytest.approx(2 / 3)
    assert ltv_distance_to_liquidation(0.915, 0.915) == 0


def test_pt_price_converges_to_underlying_at_maturity():
    assert pt_price(1.0, 0.09, 0) == 1.0
    assert pt_price(1.0, 0.09, -5) == 1.0
    assert pt_price(1.0, 0.09, 166) < pt_price(1.0, 0.09, 30) < 1.0


def test_haircut_is_convex_and_bounded():
    depth = 40e6
    costs = [haircut(s, depth) for s in (1e6, 2e6, 4e6)]
    assert costs[0] < costs[1] < costs[2]
    assert costs[2] > 2 * costs[1]  # nonlinear: doubling size more than doubles cost
    assert haircut(1e9, depth) < 1e9  # never more than the position


# --- scenario A ---------------------------------------------------------------

def test_no_shock_no_change(portfolio, snapshot, depeg_request):
    result = depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="0", pt_implied_apy_shock="0")
    assert D(result["portfolio"]["total_conditional_loss_usd"]) == 0
    for p in result["positions"]:
        assert p["gross_value_before_usd"] == p["gross_value_after_usd"]


def test_bigger_depeg_bigger_loss(portfolio, snapshot, depeg_request):
    losses = [D(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct=s)["portfolio"]["total_conditional_loss_usd"])
              for s in ("-0.01", "-0.05", "-0.10", "-0.20")]
    assert losses == sorted(losses) and len(set(losses)) == 4


def test_oracle_pass_through_drives_liquidation_risk_not_mark_loss(portfolio, snapshot, depeg_request):
    blind = by_id(depeg(portfolio, snapshot, depeg_request, oracle_pass_through_override="0"))["aave_01"]
    full = by_id(depeg(portfolio, snapshot, depeg_request, oracle_pass_through_override="1"))["aave_01"]
    assert blind["conditional_loss_usd"] == full["conditional_loss_usd"]
    assert D(blind["risk_metric"]["after"]) == D(blind["risk_metric"]["before"])
    assert D(full["risk_metric"]["after"]) < D(full["risk_metric"]["before"])


def test_morpho_exchange_rate_oracle_ignores_market_depeg(portfolio, snapshot, depeg_request):
    morpho = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="-0.40"))["morpho_01"]
    assert morpho["risk_metric"]["liquidatable"] is False
    assert D(morpho["conditional_loss_usd"]) > 0  # still loses mark-to-market value


def test_usde_backing_loss_is_invisible_to_hardcoded_exchange_rate_oracle(portfolio, snapshot, depeg_request):
    morpho = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="0", backing_impairment_pct="-0.30"))["morpho_01"]
    assert morpho["risk_metric"]["liquidatable"] is False
    assert D(morpho["loss_components"]["backing_impairment"]) > 0  # the value loss is still real


def test_susde_rate_cut_reaches_exchange_rate_oracle(portfolio, snapshot, depeg_request):
    morpho = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="0", susde_rate_cut_pct="-0.30"))["morpho_01"]
    assert morpho["risk_metric"]["liquidatable"] is True
    # Morpho has no close factor: full debt repaid x 2.6% incentive.
    assert D(morpho["loss_components"]["liquidation_penalty"]) == D("52000.00")


def test_aave_close_factor_limits_penalty(portfolio, snapshot, depeg_request):
    # USDe at 0.70: HF = 2.1m x 0.85 / 1.8m = 0.9917 >= 0.95, so only 50% of the debt is liquidated.
    aave = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="-0.30"))["aave_01"]
    assert aave["risk_metric"]["liquidatable"] is True
    assert D(aave["loss_components"]["liquidation_penalty"]) == D("45000.00")  # 0.5 x 1.8m x 5%
    deep = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="-0.40"))["aave_01"]
    assert D(deep["loss_components"]["liquidation_penalty"]) == D("90000.00")  # HF < 0.95: 100%


def test_no_liquidation_without_threshold_breach(portfolio, snapshot, depeg_request):
    # Aave breaks at USDe ~0.706 (-29.4%): just above stays safe, just below is liquidatable.
    safe = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="-0.29"))["aave_01"]
    broken = by_id(depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct="-0.30"))["aave_01"]
    assert safe["risk_metric"]["liquidatable"] is False
    assert D(safe["loss_components"]["liquidation_penalty"]) == 0
    assert broken["risk_metric"]["liquidatable"] is True


# --- scenario B ---------------------------------------------------------------

def test_liquidity_crisis_keeps_mark_value(portfolio, snapshot, liquidity_request):
    for p in simulate(portfolio, snapshot, liquidity_request)["positions"]:
        assert p["gross_value_before_usd"] == p["gross_value_after_usd"]
        assert D(p["executable_value_after_usd"]) < D(p["gross_value_after_usd"])


def test_more_liquidity_lost_bigger_haircut(portfolio, snapshot, liquidity_request):
    totals = [D(simulate(portfolio, snapshot, with_params(liquidity_request, exit_liquidity_reduction_pct=r))
                ["portfolio"]["total_conditional_loss_usd"]) for r in ("0", "0.5", "0.8", "0.95")]
    assert totals == sorted(totals)


def test_shared_venue_joint_exit_costs_more(portfolio, snapshot, liquidity_request):
    result = simulate(portfolio, snapshot, liquidity_request)
    assert D(result["portfolio"]["shared_liquidity_penalty_usd"]) > 0


def test_missing_venue_is_flagged_not_invented(portfolio, snapshot, liquidity_request):
    snap = copy.deepcopy(snapshot)
    del snap["exit_venues"]["venue:pendle_pt_susde"]
    result = simulate(portfolio, snap, liquidity_request)
    pendle = by_id(result)["pendle_01"]
    assert pendle["calculation_status"] == "insufficient_data"
    assert pendle["executable_value_after_usd"] is None
    assert result["portfolio"]["total_conditional_loss_usd"] is None


# --- reconciliation & contract --------------------------------------------------

@pytest.mark.parametrize("shock", ["-0.01", "-0.0731", "-0.25", "-0.5"])
def test_numbers_reconcile_to_the_cent(portfolio, snapshot, depeg_request, shock):
    result = depeg(portfolio, snapshot, depeg_request, usde_spot_shock_pct=shock, backing_impairment_pct="-0.033",
                   susde_rate_cut_pct="-0.021")
    total = D(0)
    for p in result["positions"]:
        loss = D(p["conditional_loss_usd"])
        assert sum(D(v) for v in p["loss_components"].values()) == loss
        assert D(p["net_equity_before_usd"]) - loss == D(p["net_equity_after_usd"])
        total += loss
    pf = result["portfolio"]
    assert total + D(pf["shared_liquidity_penalty_usd"]) == D(pf["total_conditional_loss_usd"])
    assert D(pf["net_equity_before_usd"]) - D(pf["total_conditional_loss_usd"]) == D(pf["net_equity_after_usd"])


def test_inconsistent_ids_are_rejected(portfolio, snapshot, depeg_request):
    bad = copy.deepcopy(depeg_request)
    bad["snapshot_id"] = "other_snapshot"
    with pytest.raises(ValueError, match="snapshot_id"):
        simulate(portfolio, snapshot, bad)


def test_unknown_scenario_is_rejected(portfolio, snapshot, depeg_request):
    bad = copy.deepcopy(depeg_request)
    bad["scenario"]["scenario_id"] = "oracle_freeze"
    with pytest.raises(KeyError, match="oracle_freeze"):
        simulate(portfolio, snapshot, bad)
