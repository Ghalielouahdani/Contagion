"""Free Crypto News API adapter: relevant, bounded, normalized news; never invented, never the raw question."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from backend.api import risk_news

PORTFOLIO = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01" / "portfolio.json").read_text())
NOW = datetime.now(timezone.utc)


def article(title, source="CoinDesk", days=1, link=None, description=""):
    return {"title": title, "link": link or f"https://news.example/{abs(hash(title))}", "description": description,
            "pubDate": (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z"), "source": source}


FEED = {
    "Fed": [article("Fed signals a rate cut in December"), article("Boston official charged in Federal funds fraud")],
    "Ethena": [article("Ethena's ENA slides as leverage falls"), article("Old Ethena story", days=40)],
    "USDe": [article("USDe basis trade extends to equity perpetuals")],
    "stablecoin": [article("ETH Gas: 0.06 Gwei", source="Etherscan"), article("Stablecoin supply hits a record")],
}


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or {}), headers))
        if url.endswith("/fear-greed"):
            return Response({"current": {"value": 61, "valueClassification": "Greed"}})
        return Response({"articles": FEED.get(params["q"], [])})

    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "cryptocurrency_cv")
    monkeypatch.setattr(risk_news.httpx, "get", get)
    return calls


def test_disabled_unless_configured(monkeypatch):
    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "")
    assert risk_news.fetch("anything", PORTFOLIO)["status"] == "not_configured"


def test_terms_come_from_the_question_keywords_and_the_portfolio(provider):
    result = risk_news.fetch("Et si la Fed baisse ses taux ?", PORTFOLIO)
    terms = result["market_context"]["search_terms"]
    assert terms[0] == "Fed" and {"Ethena", "USDe", "stablecoin", "Aave", "Morpho"} <= set(terms)
    sent = [params.get("q") for _, params, _ in provider]
    assert "Et si la Fed baisse ses taux ?" not in sent  # the question itself never leaves the backend
    assert all(headers["User-Agent"].startswith("defi-contagion-risk") for _, _, headers in provider)


def test_articles_are_relevant_recent_and_normalized(provider):
    result = risk_news.fetch("Fed", PORTFOLIO)
    titles = [a["title"] for a in result["articles"]]
    assert "Fed signals a rate cut in December" in titles
    assert "Boston official charged in Federal funds fraud" not in titles  # "Fed" must be a whole word
    assert "Old Ethena story" not in titles  # older than 14 days
    assert not any("Gas" in t for t in titles)  # price-tracker noise
    assert result["status"] == "provided" and result["origin"] == "cryptocurrency_cv"
    for a in result["articles"]:
        assert set(a) == {"id", "title", "summary", "url", "published_at", "source"}
        assert result["market_context"]["found_by"][a["id"]] in result["market_context"]["search_terms"]
    assert result["market_context"]["fear_greed"] == {"value": 61, "classification": "Greed"}


def test_each_topic_gets_its_turn(provider):
    result = risk_news.fetch("Fed", PORTFOLIO)
    found = set(result["market_context"]["found_by"].values())
    assert {"Fed", "Ethena", "USDe", "stablecoin"} <= found


def test_provider_down_is_explicit(monkeypatch):
    monkeypatch.setenv("RISK_NEWS_URL", "")
    monkeypatch.setenv("RISK_NEWS_PROVIDER", "cryptocurrency_cv")

    def down(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(risk_news.httpx, "get", down)
    with pytest.raises(HTTPException) as error:
        risk_news.fetch("Fed", PORTFOLIO)
    assert error.value.status_code == 502


def test_assistant_route_passes_question_and_portfolio(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import risk_assistant
    from backend.api.main import app

    seen = {}
    monkeypatch.setattr(risk_news, "fetch", lambda question=None, portfolio=None: seen.update(q=question, p=portfolio)
                        or {"status": "empty", "origin": "cryptocurrency_cv", "fetched_at": NOW.isoformat(), "articles": []})
    monkeypatch.setattr(risk_assistant, "generate", lambda body, files, validator, news: {"news": news["status"]})
    response = TestClient(app).post("/api/v1/risk/assistant?set=stress_portfolio_01", json={"message": "Si le dollar baisse ?"})
    assert response.status_code == 200, response.text
    assert seen["q"] == "Si le dollar baisse ?" and seen["p"]["portfolio_id"] == "stress_portfolio_01"
