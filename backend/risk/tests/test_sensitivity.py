"""Sensitivity: tornado ranking and loss / liquidation grids."""

import time
from decimal import Decimal as D

import pytest

from backend.risk.analytics import analyze, sensitivity
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot
from backend.risk.tests.conftest import load, with_params


@pytest.fixture
def models(portfolio, snapshot):
    return Portfolio.from_contract(portfolio), Snapshot.from_contract(snapshot)


def request_model(raw):
    return ScenarioRequest.from_contract(raw)


def row(rows, label):
    return next(r for r in rows if r["assumption"] == label)


def test_tornado_is_sorted_and_led_by_depeg_size(models, depeg_request):
    p, s = models
    rows = sensitivity.tornado(p, s, request_model(depeg_request))
    swings = [r["swing_usd"] for r in rows]
    assert swings == sorted(swings, reverse=True)
    assert rows[0]["assumption"] == "USDe depeg size"


def test_liquidation_parameters_do_not_matter_far_from_thresholds(models, depeg_request):
    p, s = models
    rows = sensitivity.tornado(p, s, request_model(depeg_request))
    assert row(rows, "aave_01 liquidation threshold")["swing_usd"] == 0
    assert row(rows, "Oracle pass-through (all markets)")["swing_usd"] == 0


def test_close_factor_cliff_shows_in_severe_tornado(models, depeg_request):
    # At -30%: LT 0.80 puts HF below 0.95 (100% liquidated, 90k); LT 0.88 keeps HF above 1 (no penalty).
    p, s = models
    severe = request_model(with_params(depeg_request, usde_spot_shock_pct="-0.30"))
    lt = row(sensitivity.tornado(p, s, severe), "aave_01 liquidation threshold")
    assert lt["swing_usd"] == pytest.approx(90_000, abs=0.01)


def test_tornado_does_not_mutate_inputs(portfolio, snapshot, depeg_request):
    before = (str(portfolio), str(snapshot), str(depeg_request))
    analyze(portfolio, snapshot, depeg_request)
    assert (str(portfolio), str(snapshot), str(depeg_request)) == before


def test_grid_maps_the_liquidation_frontier(models, depeg_request):
    p, s = models
    g = sensitivity.default_grid(p, s, request_model(depeg_request))
    counts = g["liquidatable_positions"]
    assert len(counts) == len(g["y_values"]) and len(counts[0]) == len(g["x_values"])
    assert all(c == 0 for c in counts[0])  # pass-through 0: nothing is ever liquidated by a depeg
    assert counts[-1][-1] == 2  # pass-through 1, -40%: Aave and Morpho both liquidatable
    for loss_row in g["loss_usd"]:
        assert loss_row == sorted(loss_row)  # bigger depeg, bigger loss


def test_grid_rejects_unknown_parameters(models, depeg_request):
    p, s = models
    with pytest.raises(KeyError, match="not a parameter"):
        sensitivity.grid(p, s, request_model(depeg_request), "usde_spot_shock_pct", [0.0], "exit_liquidity_reduction_pct", [0.5])


def test_liquidity_grid_and_depth_sensitivity(models, liquidity_request):
    p, s = models
    r = request_model(liquidity_request)
    g = sensitivity.default_grid(p, s, r)
    assert all(row == sorted(row) for row in g["loss_usd"])  # more liquidity lost, bigger loss
    depth = row(sensitivity.tornado(p, s, r), "venue:susde_usdc depth")
    assert depth["loss_at_low_usd"] < depth["loss_at_high_usd"]  # deeper venue (x2) costs less than shallower (x0.5)


def test_analytics_headline_names_top_driver(portfolio, snapshot, depeg_request, liquidity_request):
    assert analyze(portfolio, snapshot, depeg_request)["headline"]["top_risk_driver"] == "USDe depeg size"
    assert analyze(portfolio, snapshot, liquidity_request)["headline"]["top_risk_driver"] == "Liquidity lost in the crisis"


def test_full_grid_is_interactive(models, depeg_request):
    p, s = models
    start = time.perf_counter()
    sensitivity.grid(p, s, request_model(depeg_request), "usde_spot_shock_pct", [-i / 100 for i in range(21)],
                     "pt_implied_apy_shock", [i / 100 for i in range(21)])
    assert time.perf_counter() - start < 0.5  # 441 scenario runs
