"""Risk assistant contract boundary: model/news output cannot become unchecked simulations."""
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import risk_assistant as agent, risk_news
from backend.api.main import app, _files, _validator

client = TestClient(app)
SET = "stress_portfolio_01"


def output():
    return {"message": "Hypothèse : baisse des taux US, rendement réduit sans relation mécanique.",
            "limitations": ["La perte de pouvoir d'achat EUR n'est pas calculée par le moteur USD."],
            "scenarios": [{"title": "Baisse du rendement et dette persistante", "scenario_id": "carry_squeeze",
                           "horizon_days": 30,
                           "parameters": [{"name": "susde_apy", "value": "0.01", "rationale": "Rendement supposé pour tester ce canal."},
                                          {"name": "borrow_apy_override", "value": "0.10", "rationale": "Le taux DeFi ne suit pas forcément la Fed."}],
                           "causal_chain": ["Baisse hypothétique des taux", "Rendement sUSDe moindre", "Dette qui continue de croître"],
                           "affected_positions": ["morpho_01", "ethena_susde_01"],
                           "assumptions": ["Ces taux sont des hypothèses de stress."],
                           "unmodeled_risks": ["EUR/USD non modélisé."], "news_ids": []}]}


@pytest.fixture
def model(monkeypatch):
    value = output()
    monkeypatch.setattr(agent, "generate_model", lambda context: copy.deepcopy(value))
    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "")  # never hit the network, whatever .env enables
    return value


def call(body=None):
    return client.post(f"/api/v1/risk/assistant?set={SET}", json=body or {"message": "Si la Fed baisse ses taux ?", "count": 3})


def test_uses_server_portfolio_and_limits_external_context(monkeypatch, model):
    contexts = []
    def capture(context):
        contexts.append(context)
        return output()
    monkeypatch.setattr(agent, "generate_model", capture)
    result = call({"message": "Test", "portfolio": {"positions": [{"position_id": "fake"}]}})
    assert result.status_code == 200, result.text
    context = contexts[0]
    assert context["portfolio"]["portfolio_id"] == SET
    assert "fake" not in json.dumps(context)
    assert "oracle_address" not in json.dumps(context)
    assert "evidence" not in context["dependencies"]
    assert context["provided_news"]["status"] == "not_configured"
    assert result.json()["actions"] == []


def test_generated_case_runs_exactly_through_existing_engine(model):
    response = call()
    assert response.status_code == 200, response.text
    proposal = response.json()["proposals"][0]
    request = proposal["request"]
    assert request["scenario"]["parameters"]["susde_apy"] == "0.01"
    assert request["scenario"]["parameters"]["borrow_apy_override"] == "0.10"
    assert request["assumptions"]["probability"] is None
    assert proposal["parameters"][0]["source"] == "Model assumption"
    assert next(p for p in proposal["parameters"] if p["name"] == "pt_implied_apy_shock")["source"] == "Portfolio preset"
    risk = client.post(f"/api/v1/simulate?set={SET}", json=request)
    assert risk.status_code == 200, risk.text
    assert risk.json()["scenario_id"] == "carry_squeeze"
    assert risk.json()["horizon_days"] == 30
    assert "conditional_loss_usd" not in proposal


@pytest.mark.parametrize("change", [
    lambda r: r["scenarios"][0]["parameters"].append({"name": "eur_usd", "value": "-0.1", "rationale": "FX"}),
    lambda r: r["scenarios"][0]["parameters"][0].update(value="NaN"),
    lambda r: r["scenarios"][0]["parameters"][0].update(value="0.5"),
    lambda r: r["scenarios"][0]["parameters"][0].update(value="1%"),
    lambda r: r["scenarios"][0]["affected_positions"].append("invented_position"),
    lambda r: r["scenarios"][0]["news_ids"].append("invented_article"),
    lambda r: r["scenarios"][0].update(horizon_days=365),
    lambda r: r["scenarios"][0].update(scenario_id="invented_mechanism"),
    lambda r: r["scenarios"][0]["parameters"].append(copy.deepcopy(r["scenarios"][0]["parameters"][0])),
])
def test_rejects_bad_model_output_without_applying_any_case(model, change):
    change(model)
    assert call().status_code == 502


def article():
    return {"id": "news_1", "title": "Reported rate decision", "summary": "Reported change, supplied for testing.",
            "url": "https://example.org/article", "published_at": "2026-10-10T15:00:00Z", "source": "Supplied source"}


def test_news_attribution_comes_from_supplied_articles(model):
    model["scenarios"][0]["news_ids"] = ["news_1"]
    response = call({"message": "Analyse cette news", "news": {"articles": [article()]}})
    assert response.status_code == 200
    body = response.json()
    assert body["context"]["newsStatus"] == "provided"
    assert body["proposals"][0]["sources"] == [article()]


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "file:///etc/passwd"])
def test_rejects_non_web_news_links(model, bad):
    row = article(); row["url"] = bad
    assert call({"message": "Analyse", "news": {"articles": [row]}}).status_code == 422


def test_no_key_has_no_local_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "")
    assert client.get("/api/v1/risk/assistant-status").json()["configured"] is False
    response = call()
    assert response.status_code == 503
    assert "No local fallback" in response.json()["detail"]


def test_provider_transport_and_key_redaction(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    def respond(url, headers, json, timeout):
        assert url.endswith(":generateContent")
        assert headers["x-goog-api-key"] == "test-only-secret"
        assert "test-only-secret" not in str(json)
        assert "systemInstruction" in json
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": __import__('json').dumps(output())}]}}]})
    monkeypatch.setattr(agent.httpx, "post", respond)
    assert agent.generate_model({"event": "Hypothetical event"}) == output()
    monkeypatch.setattr(agent.httpx, "post", lambda *a, **kw: httpx.Response(400, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}}))
    response = call()
    assert response.status_code == 503
    assert "test-only-secret" not in response.text
    assert "rejected the API key" in response.json()["detail"]


def test_news_feed_is_explicitly_unconfigured(monkeypatch):
    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "")
    body = client.get("/api/v1/risk/news").json()
    assert body["status"] == "not_configured" and body["articles"] == []


def test_generation_count_and_event_bounds(model):
    for body in ({"message": "test", "count": 4}, {"message": "test", "count": True}, {"message": ""}, {"message": "a" * 6001}):
        assert call(body).status_code == 422


def test_auto_count_allows_one_useful_case_without_padding(monkeypatch):
    contexts = []
    def generate(context):
        contexts.append(context)
        return output()
    monkeypatch.setattr(agent, "generate_model", generate)
    monkeypatch.setenv("RISK_NEWS_URL", "")
    response = call({"message": "Un seul cas ciblé sur le rendement sUSDe"})
    assert response.status_code == 200, response.text
    assert len(response.json()["proposals"]) == 1
    assert contexts[0]["requested_count"] is None
    assert "Never pad to three" in contexts[0]["count_policy"]


def test_explicit_count_still_limits_generated_cases(model):
    model["scenarios"].append(copy.deepcopy(model["scenarios"][0]))
    assert call({"message": "Test", "count": 1}).status_code == 502
