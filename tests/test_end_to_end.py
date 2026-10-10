"""End to end through the API, offline: P1 discovery (replayed) -> P2 risk -> P3 decision.

Integration checkpoints 2 to 4 (tests/README.md): the discovered snapshot and graph flow into the
risk engine, its result feeds the decision engine, and every response matches schema v1.
"""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import discovery_state
from backend.api.main import app
from backend.discovery.validation import schema_errors

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "fixtures"
SET = "live_ethena_01"  # the set with a recorded discovery (backend/discovery/cassettes/live_ethena_01.json)

client = TestClient(app)


def load(name: str) -> dict:
    return json.loads((FIXTURES / SET / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def fresh_state():
    discovery_state.reset()
    yield
    discovery_state.reset()


def post(route: str, body: dict, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in {"set": SET, **params}.items())
    response = client.post(f"/api/v1/{route}?{query}", json=body)
    assert response.status_code == 200, (route, response.json())
    return response.json()


@pytest.mark.parametrize("request_name", ["scenario_request", "scenario_request_liquidity"])
def test_discovery_to_risk_to_decision(request_name):
    graph = post("discover", {"schema_version": "1.0", "portfolio_id": SET}, discovery="replay")
    assert schema_errors(graph, "dependency_graph.schema.json") == []
    assert sum(e["confidence"] == "verified" for e in graph["edges"]) > len(graph["edges"]) / 2  # read on-chain, not hand-written

    health = client.get(f"/api/v1/health?set={SET}").json()
    assert health["active_discovery"]["mode"] == "replay"

    request = load(request_name)
    risk = post("simulate", request)
    assert schema_errors(risk, "risk_result.schema.json") == []
    assert risk["provenance"]["input_graph_id"] == graph["graph_id"]
    for position in risk["positions"]:  # every loss is explained by a path in the discovered graph
        assert position["contagion"]["paths"] and position["contagion"]["graph_gaps"] == []

    analytics = post("analyze", request)
    assert schema_errors(analytics, "risk_analytics.schema.json") == []

    for position in load("portfolio")["positions"]:
        decision = post("decide", {"request": request, "position_id": position["position_id"]})
        assert schema_errors(decision, "decision_result.schema.json") == []
        assert decision["position_id"] == position["position_id"]
        assert [o["exit_fraction"] for o in decision["exit_options"]] == ["0.00", "0.25", "0.50", "0.75", "1.00"]
        # P3 consumes P2's loss for this position: staying keeps the whole conditional loss
        loss = next(p["conditional_loss_usd"] for p in risk["positions"] if p["position_id"] == position["position_id"])
        assert Decimal(decision["exit_options"][0]["residual_stress_loss_usd"]) == Decimal(loss)


def test_replayed_discovery_reproduces_the_stored_set():
    graph = post("discover", {"schema_version": "1.0"}, discovery="replay")
    assert {n["id"] for n in graph["nodes"]} == {n["id"] for n in load("dependency_graph")["nodes"]}
    snapshot = client.get(f"/api/v1/market-snapshot?set={SET}").json()
    assert snapshot == load("market_snapshot")
    risk = post("simulate", load("scenario_request"))
    stored = load("risk_result")
    assert risk["portfolio"]["total_conditional_loss_usd"] == stored["portfolio"]["total_conditional_loss_usd"]


def test_stored_mode_resets_and_unknown_modes_are_rejected():
    post("discover", {"schema_version": "1.0"}, discovery="replay")
    post("discover", {"schema_version": "1.0"}, discovery="stored")
    assert client.get(f"/api/v1/health?set={SET}").json()["active_discovery"]["mode"] == "stored"
    assert client.post(f"/api/v1/discover?set={SET}&discovery=guess", json={}).status_code == 422
    # a set without a recorded discovery cannot be replayed
    assert client.post("/api/v1/discover?set=demo_ethena_01&discovery=replay", json={}).status_code == 422


def test_requests_are_readdressed_to_the_active_discovery():
    post("discover", {"schema_version": "1.0"}, discovery="replay")
    request = copy.deepcopy(load("scenario_request"))
    request["snapshot_id"] = "snapshot_from_an_older_run"  # e.g. a frontend still holding stored ids
    risk = post("simulate", request)
    assert risk["provenance"]["input_snapshot_id"] == load("market_snapshot")["snapshot_id"]
