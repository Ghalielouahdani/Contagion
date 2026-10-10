"""Model uncertainty: the same scenario under plausible unverified assumptions gives a range, not one number."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk.analytics import analyze
from backend.risk.analytics.uncertainty import model_assumptions, position_curves, uncertainty
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot
from backend.risk.tests.test_golden import SCHEMAS

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def models(set_name: str, request: str = "scenario_request"):
    load = lambda n: json.loads((FIXTURES / set_name / f"{n}.json").read_text())  # noqa: E731
    return (Portfolio.from_contract(load("portfolio")), Snapshot.from_contract(load("market_snapshot")),
            ScenarioRequest.from_contract(load(request)))


def test_reproducible_with_a_fixed_seed():
    assert uncertainty(*models("demo_ethena_01")) == uncertainty(*models("demo_ethena_01"))


def test_percentiles_are_ordered_and_contain_the_base_case():
    u = uncertainty(*models("demo_ethena_01"))
    pf = u["portfolio"]
    assert pf["min_usd"] <= pf["p05_usd"] <= pf["p25_usd"] <= pf["p50_usd"] <= pf["p75_usd"] <= pf["p95_usd"] <= pf["max_usd"]
    assert pf["min_usd"] <= pf["base_usd"] <= pf["max_usd"]
    assert sum(b["draws"] for b in u["histogram"]) == u["draws"]
    assert set(u["positions"]) == {"ethena_susde_01", "aave_01", "morpho_01", "pendle_01"}


def test_scenario_severity_is_never_varied():
    labels = [r.assumption.target for r in model_assumptions(*models("demo_ethena_01")[1:])]
    assert "usde_spot_shock_pct" not in labels and "backing_impairment_pct" not in labels


def test_verified_markets_stay_fixed():
    portfolio, snapshot, request = models("verified_2026_10_10")
    targets = [r.assumption.target for r in model_assumptions(snapshot, request)]
    assert not any(t.startswith(("aave_01.", "morpho_01.", "pendle_01.")) for t in targets)
    assert uncertainty(portfolio, snapshot, request)["fixed_because_verified"] == ["aave_01", "morpho_01", "pendle_01"]


def test_depeg_range_is_driven_by_susde_beta():
    # demo -5%: sUSDe (4.0m of sUSDe-linked value) moves 1:1 with beta; nothing is liquidated in any draw.
    u = uncertainty(*models("demo_ethena_01"))
    assert u["drivers"][0]["assumption"] == "sUSDe beta to USDe" and u["drivers"][0]["rank_correlation"] > 0.95
    assert u["liquidatable_positions_share"] == {"0": 1.0}


def test_cascade_single_number_sits_in_the_upper_tail():
    # The lender's cascade loss (377k) depends on unverified oracle types and arbitrage: most draws lose nothing.
    u = uncertainty(*models("demo_lending_01", "scenario_request_cascade"))
    assert u["portfolio"]["p50_usd"] == 0 < u["portfolio"]["base_usd"]
    assert u["portfolio"]["max_usd"] > u["portfolio"]["base_usd"]


def test_position_curves_follow_the_main_axis():
    curves = position_curves(*models("demo_ethena_01"))
    assert curves["x_param"] == "usde_spot_shock_pct"
    totals = curves["total_usd"]
    for j, total in enumerate(totals):
        assert sum(curves["positions_usd"][p][j] for p in curves["positions_usd"]) == pytest.approx(total)


def test_analytics_with_uncertainty_validate_against_schema():
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((SCHEMAS / "risk_analytics.schema.json").read_text()), registry=registry)
    load = lambda n: json.loads((FIXTURES / "demo_lending_01" / f"{n}.json").read_text())  # noqa: E731
    result = analyze(load("portfolio"), load("market_snapshot"), load("scenario_request_cascade"))
    assert not [e.message for e in validator.iter_errors(result)]
