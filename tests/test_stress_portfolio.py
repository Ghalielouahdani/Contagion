"""The unified portfolio exercises distinct risk channels on recorded real markets."""

import json
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import app

ROOT = Path(__file__).resolve().parents[1] / "contracts" / "fixtures" / "stress_portfolio_01"


def run(suffix="", **parameters):
    request = json.loads((ROOT / f"scenario_request{suffix}.json").read_text())
    request["scenario"]["parameters"].update(parameters)
    client = TestClient(app)
    response = client.post("/api/v1/simulate?set=stress_portfolio_01", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    for impact in result["positions"]:
        response = client.post("/api/v1/decide?set=stress_portfolio_01", json={
            "simulation_id": result["simulation_id"], "position_id": impact["position_id"],
        })
        assert response.status_code == 200, response.text
        decision = response.json()
        assert decision["simulation_id"] == result["simulation_id"]
        assert decision["portfolio_id"] == "stress_portfolio_01"
        assert Decimal(decision["exit_options"][0]["residual_stress_loss_usd"]) == Decimal(impact["conditional_loss_usd"])
    return result, {p["position_id"]: p for p in result["positions"]}


def test_mild_depeg_distinguishes_oracles_and_lender_losses():
    _, positions = run()
    assert not positions["aave_01"]["risk_metric"]["liquidatable"]
    assert positions["morpho_01"]["risk_metric"]["liquidatable"]
    assert Decimal(positions["ethena_susde_01"]["conditional_loss_usd"]) > 0
    for pid in ("lend_susde_01", "lend_usde_01"):
        assert Decimal(positions[pid]["loss_components"]["bad_debt"]) == 0
        assert not positions[pid]["contagion"]["unmodeled_exposures"]


def test_cascade_hurts_lenders_and_amplifies_the_same_portfolio_shock():
    baseline, _ = run()
    cascade, positions = run("_cascade")
    assert Decimal(cascade["portfolio"]["total_conditional_loss_usd"]) > Decimal(baseline["portfolio"]["total_conditional_loss_usd"])
    assert Decimal(positions["lend_susde_01"]["conditional_loss_usd"]) > 0
    assert Decimal(positions["lend_usde_01"]["conditional_loss_usd"]) > 0
    assert {p["position_id"] for p in baseline["positions"]} == set(positions)


def test_long_carry_squeeze_crosses_morpho_threshold_without_price_shock():
    _, positions = run("_carry")
    assert positions["morpho_01"]["risk_metric"]["liquidatable"]
    assert not positions["aave_01"]["risk_metric"]["liquidatable"]
    assert Decimal(positions["ethena_susde_01"]["conditional_loss_usd"]) == 0
