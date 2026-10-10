import json

import pytest

from backend.execution.decision import FIXTURE_DIR, load_contracts
from backend.execution.entrypoint import handle_decide_request

BASE = {"schema_version": "1.0", "portfolio_id": "demo_ethena_01", "position_id": "aave_01", "scenario_id": "usde_depeg"}


def call(**changes):
    request = {**BASE, **changes}
    return handle_decide_request({k: v for k, v in request.items() if v is not ...})


def test_fixture_mode_returns_the_golden_decision():
    status, body = call()
    assert (status, body["status"], body["mode"]) == (200, "ok", "fixture")
    assert body["decision"] == json.loads((FIXTURE_DIR / "decision_result.json").read_text())


def test_user_probability_drives_the_recommendation():
    status, body = call(probability="0.15")
    assert status == 200
    assert (body["decision"]["mode"], body["decision"]["recommendation"]) == ("expected_cost", "REDUCE")


def test_liquidity_scenario_and_optional_blocks():
    status, body = call(scenario_id="liquidity_crisis", include=["sensitivity", "portfolio_summary"])
    assert status == 200
    assert body["decision"]["decision_id"] == "decision_sim_002"
    assert len(body["sensitivity"]["objective_vs_probability"]["probabilities"]) == 51
    assert body["portfolio_summary"]["scenario_id"] == "liquidity_crisis"


def test_live_mode_uses_the_inputs_sent_by_p4():
    c = load_contracts()
    inputs = {"portfolio": c["portfolio"], "market_snapshot": c["snapshot"],
              "risk_result": c["risk_result"], "scenario_request": c["scenario_request"]}
    inputs["risk_result"]["positions"][1]["conditional_loss_usd"] = "300000.00"   # aave_01 : perte doublée
    status, body = call(scenario_id=..., inputs=inputs)
    assert (status, body["mode"]) == (200, "live")
    assert body["decision"]["exit_options"][0]["residual_stress_loss_usd"] == "300000.00"


@pytest.mark.parametrize("changes, status, code", [
    ({"schema_version": "2.0"}, 400, "unsupported_schema_version"),
    ({"portfolio_id": "other"}, 404, "unknown_portfolio"),
    ({"position_id": "nope_01"}, 404, "unknown_position"),
    ({"position_id": ...}, 422, "invalid_request"),
    ({"scenario_id": "oracle_freeze"}, 422, "invalid_request"),
    ({"include": ["charts"]}, 422, "invalid_request"),
    ({"scenario_id": ..., "inputs": {"portfolio": {}}}, 422, "invalid_request"),
    ({"probability": "1.5"}, 422, "invalid_inputs"),
    ({"probability": "abc"}, 422, "invalid_request"),
    ({"probability": 0.15}, 422, "invalid_request"),          # nombre JSON : la convention impose une chaîne
])
def test_bad_requests_get_a_clear_error_not_a_crash(changes, status, code):
    got_status, body = call(**changes)
    assert (got_status, body["status"], body["error"]["code"]) == (status, "error", code)
    assert body["error"]["message"]


def test_non_object_body_is_rejected():
    assert handle_decide_request(["not", "a", "dict"])[0] == 422
