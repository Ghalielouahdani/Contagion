import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.execution.advisor import OUTPUT_SCHEMA, SYSTEM, GeminiClient, advise
from backend.execution.crisis import CrisisModel

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def inputs(suffix="_combined"):
    return load("portfolio.json"), load("market_snapshot.json"), load(f"scenario_request{suffix}.json"), \
        load(f"risk_result{suffix}.json")


def answer(**changes):
    """Réponse d'IA valide : 3 stratégies composées d'actions disponibles, sans montant dans le texte."""
    base = {
        "scenario_explanation": "The depeg and the thinner exit pools hit the USDe-linked positions.",
        "position_assessments": [{"position_id": "morpho_01", "situation": "Liquidatable.", "key_risk": "Penalty."}],
        "strategies": [
            {"name": "Exit the loss makers early", "timing": "early", "rationale": "Act before the move.",
             "pros": ["Avoids the price loss."], "cons": ["Pays crisis exit costs."],
             "actions": [{"position_id": "aave_01", "action": "sell", "fraction": "1.00", "rationale": "Largest loss."},
                         {"position_id": "lend_susde_01", "action": "withdraw", "fraction": "1.00", "rationale": "Bad debt."}]},
            {"name": "Keep core, deleverage Morpho", "timing": "early", "rationale": "Conviction on Ethena.",
             "pros": ["Keeps yield."], "cons": ["Keeps price risk."],
             "actions": [{"position_id": "morpho_01", "action": "deleverage", "fraction": "none", "rationale": "Avoid penalty."}]},
            {"name": "Late damage control", "timing": "late", "rationale": "Market already moved.",
             "pros": ["Avoids the penalty."], "cons": ["Price loss incurred."],
             "actions": [{"position_id": "morpho_01", "action": "sell", "fraction": "1.00", "rationale": "Penalty."}]},
        ],
        "recommended_strategy_index": 0,
        "recommendation_rationale": "Largest saving for a modest exit cost.",
        "hedging_notes": ["Short USDe perpetuals: not priced."],
        "caveats": ["Exit costs extrapolated beyond quoted sizes."],
    }
    base.update(changes)
    return base


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, system, context, schema):
        self.calls.append((system, context, schema))
        return copy.deepcopy(self.reply)


def test_strategies_are_recomputed_by_the_engine_not_taken_from_the_ai():
    llm = FakeLLM(answer())
    out = advise(*inputs(), llm=llm)
    assert out["advice_error"] is None
    model = CrisisModel(*inputs())
    first = out["advice"]["strategies"][0]
    expected = model.evaluate("early", {"aave_01": ("sell", "1.00"), "lend_susde_01": ("withdraw", "1.00")})
    assert first["computed_result"]["total_loss_usd"] == expected["total_loss_usd"]
    assert out["advice"]["recommended_strategy"] == "Exit the loss makers early"
    assert out["advice"]["ungrounded_numbers"] == []


def test_context_holds_computed_figures_but_no_secrets_or_addresses():
    llm = FakeLLM(answer())
    advise(*inputs(), llm=llm)
    system, context, schema = llm.calls[0]
    assert system == SYSTEM and schema == OUTPUT_SCHEMA
    text = json.dumps(context)
    assert "0x" not in text and "API_KEY" not in text
    assert {p["position_id"] for p in context["positions"]} == {p["position_id"] for p in load("portfolio.json")["positions"]}
    assert context["hedging"]["usable_hedge_assets"] == ["USDC"]


def test_unavailable_action_rejects_the_advice_but_keeps_the_plan():
    bad = answer()
    bad["strategies"][2]["actions"] = [{"position_id": "lend_usde_01", "action": "withdraw", "fraction": "1.00",
                                        "rationale": "Late withdrawal is not modelled."}]
    out = advise(*inputs(), llm=FakeLLM(bad))
    assert out["advice"] is None
    assert "unavailable action" in out["advice_error"]["message"]
    assert out["plan"]["strategies"]["early"]                     # le plan calculé reste affichable


def test_unknown_position_and_schema_violations_are_rejected():
    ghost = answer()
    ghost["strategies"][0]["actions"][0]["position_id"] = "ghost_01"
    assert "unknown position" in advise(*inputs(), llm=FakeLLM(ghost))["advice_error"]["message"]
    two = answer(strategies=answer()["strategies"][:2])           # il en faut exactement 3
    assert "schema" in advise(*inputs(), llm=FakeLLM(two))["advice_error"]["message"]


def test_invented_numbers_are_flagged():
    invented = answer(recommendation_rationale="This saves 987654.32 USD.")
    out = advise(*inputs(), llm=FakeLLM(invented))
    assert "987654.32" in out["advice"]["ungrounded_numbers"]
    grounded = answer(recommendation_rationale="Ethena is kept at 75% because the pool is shared.")
    assert advise(*inputs(), llm=FakeLLM(grounded))["advice"]["ungrounded_numbers"] == []


def test_rejected_api_key_gives_a_clear_error(monkeypatch):
    import httpx

    body = {"error": {"code": 400, "details": [{"reason": "API_KEY_INVALID"}]}}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json=body))
    out = advise(*inputs(), llm=GeminiClient(api_key="not-a-real-key", model="gemini-test"))
    assert out["advice_error"]["status"] == 503
    assert "rejected the API key" in out["advice_error"]["message"]


def test_missing_api_key_gives_a_clear_error_without_network():
    out = advise(*inputs(), llm=GeminiClient(api_key=""))
    assert out["advice_error"] == {"status": 503, "message": "AI advisor requires GEMINI_API_KEY on the backend."}
