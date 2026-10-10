"""Calculation traces: every published number can be followed from its inputs (backend/risk/trace.py)."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk import simulate
from backend.risk.tests.test_golden import SCHEMAS

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
SOURCES = {"observed", "derived", "assumed", "fictional", "user_scenario", "protocol_rule", "verified"}
RUNS = [(folder.name, request.name) for folder in sorted(FIXTURES.iterdir()) for request in sorted(folder.glob("scenario_request*.json"))]


def run(set_name: str, request_name: str) -> dict:
    load = lambda n: json.loads((FIXTURES / set_name / n).read_text())  # noqa: E731
    return simulate(load("portfolio.json"), load("market_snapshot.json"), load(request_name), load("dependency_graph.json"))


def step(trace: list[dict], step_id: str) -> dict:
    return next(s for s in trace if s["id"] == step_id)


def value(s: dict, name: str) -> D:
    return D(next(i for i in s["inputs"] if i["name"] == name)["value"])


@pytest.fixture(scope="module")
def validator():
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(json.loads((SCHEMAS / "risk_result.schema.json").read_text()), registry=registry)


@pytest.mark.parametrize("set_name, request_name", RUNS)
def test_traces_reconcile_and_validate(set_name, request_name, validator):
    result = run(set_name, request_name)
    assert not [e.message for e in validator.iter_errors(result)]
    for position in result["positions"]:
        last = position["trace"][-1]
        assert last["id"] == "loss" and last["result"]["value"] == position["conditional_loss_usd"]
        assert sum(D(i["value"]) for i in last["inputs"]) == D(position["conditional_loss_usd"])
        for s in position["trace"]:
            assert all(i["source"] in SOURCES for i in s["inputs"]), (s["id"], s["inputs"])
    aggregation = result["trace"][-1]
    assert aggregation["id"] == "portfolio_loss"
    if result["portfolio"]["total_conditional_loss_usd"] is not None:
        assert sum(D(i["value"]) for i in aggregation["inputs"]) == D(result["portfolio"]["total_conditional_loss_usd"])


def test_health_factor_step_recomputes_from_its_inputs():
    # Depeg -5% on demo_ethena_01: HF = 2,850,000 x 0.85 / 1,800,000 = 1.345833.
    hf = step(next(p for p in run("demo_ethena_01", "scenario_request.json")["positions"] if p["position_id"] == "aave_01")["trace"], "metric")
    recomputed = value(hf, "oracle collateral") * value(hf, "liquidation threshold") / value(hf, "debt")
    assert D(hf["result"]["value"]) == recomputed.quantize(D("0.000001"))
    assert hf["result"]["value"] == "1.345833"


def test_price_step_shows_the_shock_formula():
    trace = next(p for p in run("demo_ethena_01", "scenario_request.json")["positions"] if p["position_id"] == "ethena_susde_01")["trace"]
    price = step(trace, "price:sUSDe")
    assert value(price, "USDe spot shock") == D("-0.05") and price["result"]["value"] == "1.187500"  # 1.25 x 0.95
    assert next(i for i in price["inputs"] if i["name"] == "USDe spot shock")["source"] == "user_scenario"


def test_lender_trace_lists_each_borrower_bucket():
    lender = next(p for p in run("demo_lending_01", "scenario_request.json")["positions"] if p["position_id"] == "lend_usde_01")
    s = step(lender["trace"], "lender_loss")
    # Buckets 0.80 / 0.86 / 0.90 liquidated: 0.6335M + 1.8668M + 2.0045M (rows rounded one by one).
    assert len(s["rows"]) == 5 and sum(D(r["bad_debt_usd"]) for r in s["rows"]) == D("4504888.41")
    assert D(s["result"]["value"]) == D("187703.68")


def test_shared_venue_penalty_is_a_portfolio_step():
    result = run("demo_ethena_01", "scenario_request_liquidity.json")
    penalty = step(result["trace"], "shared_liquidity_penalty")
    assert penalty["result"]["value"] == result["portfolio"]["shared_liquidity_penalty_usd"] == "251015.13"


def test_exit_steps_say_how_the_cost_was_priced():
    positions = run("live_ethena_01", "scenario_request_liquidity.json")["positions"]
    labels = [s["label"] for p in positions for s in p["trace"] if s["id"].startswith("exit:")]
    assert labels and all(("quoted" in l) or ("extrapolated" in l) or ("proxy" in l) for l in labels)
    quoted = next(s for p in positions for s in p["trace"] if s["id"] == "exit:venue:susde_usdc")
    assert quoted["rows"]  # the executable quotes behind the cost
