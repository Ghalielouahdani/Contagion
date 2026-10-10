"""API routes used by the frontend (frontend/src/data/api.ts)."""

import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.risk.tests.conftest import load
from backend.risk.tests.test_golden import assert_same

client = TestClient(app)


def test_health_lists_sets_and_modules():
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["modules"]["risk"] == "live"
    assert {"demo_ethena_01", "verified_2026_10_10"} <= set(body["fixture_sets"])


def test_portfolio_graph_and_snapshot_follow_the_selected_set():
    assert client.get("/api/v1/portfolio").json()["portfolio_id"] == "demo_ethena_01"
    assert client.get("/api/v1/portfolio?set=verified_2026_10_10").json()["portfolio_id"] == "verified_ethena_01"
    graph = client.post("/api/v1/discover", json={"schema_version": "1.0", "portfolio_id": "demo_ethena_01"}).json()
    assert graph["graph_id"] == "graph_demo_01"
    assert client.get("/api/v1/market-snapshot?set=verified_2026_10_10").json()["block_number"] == 26161879
    assert client.get("/api/v1/portfolio?set=nope").status_code == 404


@pytest.mark.parametrize("request_name, golden", [("scenario_request", "risk_result"), ("scenario_request_liquidity", "risk_result_liquidity")])
def test_simulate_runs_the_engine_and_matches_golden(request_name, golden):
    response = client.post("/api/v1/simulate", json=load(request_name))
    assert response.status_code == 200
    assert_same(response.json(), load(golden))


def test_slider_values_change_the_result():
    request = copy.deepcopy(load("scenario_request"))
    request["scenario"]["parameters"]["usde_spot_shock_pct"] = "-0.20"
    body = client.post("/api/v1/simulate", json=request).json()
    assert D(body["portfolio"]["total_conditional_loss_usd"]) > D("523320.57") * 3


def test_invalid_request_is_rejected_with_reasons():
    request = copy.deepcopy(load("scenario_request"))
    request["scenario"]["parameters"]["usde_spot_shock_pct"] = -0.2  # float, not a decimal string
    response = client.post("/api/v1/simulate", json=request)
    assert response.status_code == 422
    assert any("usde_spot_shock_pct" in e for e in response.json()["detail"]["errors"])


def test_decide_follows_the_simulation_and_matches_golden_decision():
    simulation = client.post("/api/v1/simulate", json=load("scenario_request")).json()
    body = {"schema_version": "1.0", "portfolio_id": "demo_ethena_01", "simulation_id": simulation["simulation_id"], "position_id": "aave_01"}
    decision = client.post("/api/v1/decide", json=body).json()
    golden = load("decision_result")
    for key in ("reason", "warnings", "decision_id"):
        golden.pop(key)
    assert_same(decision, golden)


def test_decide_with_probability_recommends_an_action():
    request = copy.deepcopy(load("scenario_request"))
    request["assumptions"]["probability"] = "0.5"
    decision = client.post("/api/v1/decide", json={"request": request, "position_id": "aave_01"}).json()
    assert decision["mode"] == "expected_cost"
    assert decision["recommendation"] in ("REDUCE", "EXIT")


def test_analyze_and_grid():
    analytics = client.post("/api/v1/analyze", json=load("scenario_request")).json()
    assert analytics["headline"]["usde_effective_leverage"] == "1.6129"
    heat = client.post("/api/v1/grid", json={"request": load("scenario_request"), "x_param": "usde_spot_shock_pct",
                                             "x_values": [0, -0.1, -0.3], "y_param": "oracle_pass_through_override", "y_values": [0, 1]}).json()
    assert heat["liquidatable_positions"][1][2] == 2


def test_assistant_is_client_side():
    assert client.post("/api/v1/assistant", json={}).status_code == 501


@pytest.mark.parametrize("set_name", ["demo_ethena_01", "verified_2026_10_10"])
@pytest.mark.parametrize("suffix", ["", "_liquidity", "_combined", "_governance", "_carry", "_node_shock"])
def test_every_scenario_runs_end_to_end(set_name, suffix):
    request = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / set_name / f"scenario_request{suffix}.json").read_text())
    for route, body in (("simulate", request), ("analyze", request), ("decide", {"request": request, "position_id": "morpho_01"})):
        response = client.post(f"/api/v1/{route}?set={set_name}", json=body)
        assert response.status_code == 200, (route, response.json())


def test_all_dashboard_presets_feed_matching_portfolio_graph_and_decisions():
    root = Path(__file__).resolve().parents[3] / 'contracts' / 'fixtures'
    for folder in sorted(root.iterdir()):
        if not (folder / 'manifest.json').is_file():
            continue
        query = f'?set={folder.name}'
        portfolio = client.get('/api/v1/portfolio' + query).json()
        graph = client.post('/api/v1/discover' + query, json={'schema_version': '1.0'}).json()
        assert graph['portfolio_id'] == portfolio['portfolio_id']
        for path in folder.glob('scenario_request*.json'):
            request = json.loads(path.read_text())
            response = client.post('/api/v1/simulate' + query, json=request)
            assert response.status_code == 200, (folder.name, path.name, response.text)
            risk = response.json()
            assert risk['portfolio_id'] == portfolio['portfolio_id']
            assert risk['provenance']['input_graph_id'] == graph['graph_id']
            analytics = client.post('/api/v1/analyze' + query, json=request)
            assert analytics.status_code == 200, (folder.name, path.name, analytics.text)
            for position in portfolio['positions']:
                response = client.post('/api/v1/decide' + query, json={'request': request, 'position_id': position['position_id']})
                assert response.status_code == 200, (folder.name, path.name, response.text)
                decision = response.json()
                assert decision['position_id'] == position['position_id']
                assert decision['portfolio_id'] == portfolio['portfolio_id']
                assert decision['scenario_id'] == risk['scenario_id']
