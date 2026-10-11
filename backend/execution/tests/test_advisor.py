import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.execution.advisor import OUTPUT_SCHEMA, SYSTEM, GeminiClient, advise
from backend.execution.crisis import CrisisModel, min_loss_choices

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


# --- Nouveauté et cohérence du discours ---

class SequenceLLM:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, context, schema):
        self.calls.append(context)
        return copy.deepcopy(self.replies[min(len(self.calls), len(self.replies)) - 1])


def copied_candidates(suffix="_combined"):
    """Réponse qui recopie trois stratégies calculées par le code."""
    from backend.execution.crisis import crisis_plan
    plan = crisis_plan(*inputs(suffix), include_strategies=True)
    picks = [("early", "min_loss"), ("early", "protect_liquidations"), ("late", "min_loss")]
    strategies = []
    for timing, sid in picks:
        s = next(x for x in plan["strategies"][timing] if x["strategy_id"] == sid)
        actions = [{"position_id": pid, "action": c["action"], "fraction": c["fraction"] or "none", "rationale": "Copied."}
                   for pid, c in s["choices"].items() if c["action"] != "hold"]
        strategies.append({"name": sid, "timing": timing, "actions": actions, "rationale": "Copied.", "pros": [], "cons": []})
    return answer(strategies=strategies)


def test_copying_all_candidates_triggers_one_retry_with_feedback():
    llm = SequenceLLM(copied_candidates(), answer())
    out = advise(*inputs(), llm=llm)
    assert len(llm.calls) == 2 and "feedback" in llm.calls[1] and "feedback" not in llm.calls[0]
    advice = out["advice"]
    assert advice["retried_for_novelty"] is True
    assert any(s["matches_candidate"] is None for s in advice["strategies"])
    assert "copy computed candidate" not in " ".join(advice["consistency_warnings"])


def test_still_copying_after_the_retry_is_flagged_not_rejected():
    llm = SequenceLLM(copied_candidates(), copied_candidates())
    advice = advise(*inputs(), llm=llm)["advice"]
    assert len(llm.calls) == 2
    assert [s["matches_candidate"] for s in advice["strategies"]] == ["min_loss", "protect_liquidations", "min_loss"]
    assert "All three AI strategies copy computed candidate strategies." in advice["consistency_warnings"]


def test_novel_answer_is_not_retried():
    llm = SequenceLLM(answer())
    advice = advise(*inputs(), llm=llm)["advice"]
    assert len(llm.calls) == 1 and advice["retried_for_novelty"] is False


def test_claiming_an_available_exit_is_impossible_is_flagged():
    wrong = answer(position_assessments=[{"position_id": "lend_susde_01", "situation": "Lender exposed to bad debt.",
                                          "key_risk": "Inability to withdraw fully without exhausting reserves."}])
    warnings = advise(*inputs(), llm=FakeLLM(wrong))["advice"]["consistency_warnings"]
    assert any(w.startswith("lend_susde_01: the AI says the position cannot be exited") for w in warnings)


def test_rate_changes_are_flagged_only_when_the_scenario_has_no_rate_parameter():
    text = "Losses come from the depeg, thinner exit pools and interest rate changes."
    combined = advise(*inputs(), llm=FakeLLM(answer(scenario_explanation=text)))["advice"]["consistency_warnings"]
    assert "The explanation mentions rate changes, but this scenario sets no rate parameter." in combined
    carry_answer = answer(scenario_explanation=text, strategies=[
        {"name": n, "timing": "early", "rationale": "r", "pros": [], "cons": [],
         "actions": [{"position_id": "aave_01", "action": "sell", "fraction": f, "rationale": "r"}]}
        for n, f in (("A", "0.25"), ("B", "0.50"), ("C", "0.75"))])
    carry = advise(*inputs("_carry"), llm=FakeLLM(carry_answer))["advice"]["consistency_warnings"]
    assert not any("rate changes" in w for w in carry)


def test_recommending_a_costlier_strategy_is_flagged_with_the_gap():
    costly = answer(recommended_strategy_index=1)          # « Keep core, deleverage Morpho » perd bien plus
    advice = advise(*inputs(), llm=FakeLLM(costly))["advice"]
    gap = [w for w in advice["consistency_warnings"] if w.startswith("The recommended strategy loses")]
    assert gap and "(early)" in gap[0]
    assert advice["recommended_strategy"] == "Keep core, deleverage Morpho"   # signalé, pas remplacé


def test_recommending_the_lowest_loss_strategy_is_not_flagged():
    model = CrisisModel(*inputs())
    best = answer(strategies=[
        {"name": "Min loss", "timing": "early", "rationale": "r", "pros": [], "cons": [],
         "actions": [{"position_id": pid, "action": c[0], "fraction": c[1] or "none", "rationale": "r"}
                     for pid, c in min_loss_choices(model, "early").items() if c[0] != "hold"]},
        *answer()["strategies"][1:]], recommended_strategy_index=0)
    advice = advise(*inputs(), llm=FakeLLM(best))["advice"]
    assert not any(w.startswith("The recommended strategy loses") for w in advice["consistency_warnings"])


def test_late_strategy_total_is_made_comparable_with_early_ones():
    # A late total leaves out the price loss already incurred; ranking it next to early totals would mislead.
    out = advise(*inputs(), llm=FakeLLM(answer()))
    incurred = sum(D(row["late"]["already_incurred_usd"]) for row in out["plan"]["positions"])
    late = next(s for s in out["advice"]["strategies"] if s["timing"] == "late")["computed_result"]
    assert D(late["already_incurred_usd"]) == incurred > 0
    assert D(late["total_including_incurred_usd"]) == D(late["total_loss_usd"]) + incurred
    early = next(s for s in out["advice"]["strategies"] if s["timing"] == "early")["computed_result"]
    assert "total_including_incurred_usd" not in early


def test_the_ai_is_given_the_loss_mechanism_not_only_totals():
    llm = FakeLLM(answer())
    advise(*inputs("_cascade"), llm=llm)
    system, context, _ = llm.calls[0]
    morpho = next(p for p in context["positions"] if p["position_id"] == "morpho_01")
    assert morpho["loss_components"]  # e.g. market_repricing, liquidation_penalty
    assert all(D(v) != 0 for v in morpho["loss_components"].values())
    assert context["cascade"]["amplification"] is not None  # the feedback loop it must explain
    assert "total_including_incurred_usd" in system and "loss_components" in system


def test_gemini_request_is_deterministic(monkeypatch):
    import httpx

    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, **k: sent.update(k["json"]) or httpx.Response(500))
    advise(*inputs(), llm=GeminiClient(api_key="test-key", model="gemini-test"))
    assert sent["generationConfig"]["temperature"] == 0 and "seed" in sent["generationConfig"]


def test_loss_components_given_to_the_ai_add_up_to_the_loss_if_kept():
    # Holding sells nothing: the forced-sale haircut is not part of what keeping costs.
    llm = FakeLLM(answer())
    advise(*inputs("_liquidity"), llm=llm)
    for p in llm.calls[0][1]["positions"]:
        assert "execution_haircut" not in p["loss_components"]
        assert sum(D(v) for v in p["loss_components"].values()) == pytest.approx(D(p["loss_if_kept_usd"]), abs=D("0.02"))
