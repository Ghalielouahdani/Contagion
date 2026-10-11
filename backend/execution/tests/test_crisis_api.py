import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.execution.advisor as advisor
from backend.api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01"
SET = "?set=stress_portfolio_01"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")   # jamais d'appel réseau dans les tests, même si .env a une clé
    return TestClient(app)


def request(suffix="_combined"):
    return json.loads((FIXTURES / f"scenario_request{suffix}.json").read_text())


def test_plan_only_returns_positions_strategies_and_hedging(client):
    response = client.post(f"/api/v1/crisis-advice{SET}", json={"request": request(), "advice": False})
    assert response.status_code == 200
    body = response.json()
    assert body["advice"] is None and body["advice_error"] is None
    plan = body["plan"]
    assert plan["scenario_id"] == "combined_crisis" and len(plan["positions"]) == 6
    assert {s["strategy_id"] for s in plan["strategies"]["early"]} >= {"hold_all", "exit_all", "min_loss"}
    assert "hedging" in plan


def test_ai_failure_keeps_the_plan_and_explains_why(client):
    body = client.post(f"/api/v1/crisis-advice{SET}", json={"request": request()}).json()
    assert body["plan"]["positions"]
    assert body["advice"] is None
    assert body["advice_error"]["message"] == "AI advisor requires GEMINI_API_KEY on the backend."


def test_saved_simulation_is_reused(client, monkeypatch):
    run = client.post(f"/api/v1/simulate{SET}", json=request("_cascade")).json()
    seen = {}

    def fake_advise(portfolio, snapshot, scenario_request, risk_result, llm, quote_source):
        seen["simulation_id"] = risk_result["simulation_id"]
        return {"plan": {}, "advice": None, "advice_error": None}

    monkeypatch.setattr("backend.api.main.crisis_advise", fake_advise)
    response = client.post(f"/api/v1/crisis-advice{SET}", json={"simulation_id": run["simulation_id"]})
    assert response.status_code == 200 and seen["simulation_id"] == run["simulation_id"]


def test_unknown_simulation_is_a_404(client):
    response = client.post(f"/api/v1/crisis-advice{SET}", json={"simulation_id": "nope"})
    assert response.status_code == 404
