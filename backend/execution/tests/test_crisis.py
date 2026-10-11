import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.execution.crisis import crisis_plan

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01"
SCENARIOS = ["", "_liquidity", "_combined", "_carry", "_governance", "_node_shock", "_cascade", "_severe"]


def load(name):
    return json.loads((FIXTURES / name).read_text())


def plan(suffix=""):
    return crisis_plan(load("portfolio.json"), load("market_snapshot.json"),
                       load(f"scenario_request{suffix}.json"), load(f"risk_result{suffix}.json"))


def row(p, position_id):
    return next(r for r in p["positions"] if r["position_id"] == position_id)


def option(block, action, fraction=None):
    return next(o for o in block["options"] if o["action"] == action and o["fraction"] == fraction)


@pytest.mark.parametrize("suffix", SCENARIOS)
def test_every_scenario_prices_every_position(suffix):
    p = plan(suffix)
    assert len(p["positions"]) == 6
    for r in p["positions"]:
        for block in (r["early"], r["late"]):
            assert block["options"][0]["action"] == "hold"
            for o in block["options"]:   # total = coût de sortie + rendement perdu + perte restante
                assert D(o["total_loss_usd"]) == pytest.approx(
                    D(o["exit_cost_usd"]) + D(o["foregone_yield_usd"]) + D(o["residual_loss_usd"]), abs=D("0.02"))


def test_pure_liquidity_crisis_means_keep():
    # Sans choc de prix, garder ne perd rien ; vendre dans une pool à 20 % de profondeur ne fait que coûter.
    p = plan("_liquidity")
    assert all(r["holding_loss_usd"] == "0.00" for r in p["positions"])
    for pid in ["ethena_susde_01", "pendle_01"]:
        assert row(p, pid)["early"]["best"]["action"] == "hold"


def test_exits_are_priced_at_the_scenario_depth():
    calm, crisis = row(plan(""), "ethena_susde_01"), row(plan("_combined"), "ethena_susde_01")   # k = 1 puis 0.2
    assert D(option(crisis["early"], "sell", "1.00")["exit_cost_usd"]) > D(option(calm["early"], "sell", "1.00")["exit_cost_usd"])


def test_thin_pool_makes_a_partial_exit_best():
    pendle = row(plan(""), "pendle_01")["early"]
    assert pendle["best"]["action"] == "sell" and pendle["best"]["fraction"] == "0.25"
    assert D(option(pendle, "sell", "1.00")["total_loss_usd"]) > D(pendle["best"]["total_loss_usd"])


def test_late_reaction_never_counts_the_sunk_loss_as_avoidable():
    for suffix in SCENARIOS:
        for r in plan(suffix)["positions"]:
            late = r["late"]
            hold = late["options"][0]
            # Garder tard ne coûte que la pénalité restante ; la perte de prix est affichée comme déjà subie.
            assert D(hold["total_loss_usd"]) + D(late["already_incurred_usd"]) == pytest.approx(D(r["holding_loss_usd"]), abs=D("0.02"))


def test_late_deleverage_saves_the_liquidation_penalty():
    aave = row(plan("_governance"), "aave_01")   # le changement de gouvernance rend Aave liquidable
    assert D(aave["late"]["best"]["saving_vs_hold_usd"]) > 10000
    holding = row(plan(""), "ethena_susde_01")   # simple détention : rien à sauver une fois le prix tombé
    assert holding["late"]["best"]["action"] == "hold"


def test_carry_is_not_counted_twice_in_carry_squeeze():
    aave = row(plan("_carry"), "aave_01")   # le scénario contient déjà negative_carry
    assert all(o["foregone_yield_usd"] == "0.00" for o in aave["early"]["options"])


def test_lenders_withdraw_early_but_not_late():
    lender = row(plan("_cascade"), "lend_susde_01")
    assert lender["early"]["best"]["action"] == "withdraw"
    assert D(lender["early"]["best"]["saving_vs_hold_usd"]) > 800000
    assert [o["action"] for o in lender["late"]["options"]] == ["hold"]


def test_risk_result_from_another_request_is_rejected():
    request = load("scenario_request.json")
    with pytest.raises(ValueError, match="does not belong"):
        crisis_plan(load("portfolio.json"), load("market_snapshot.json"), request, load("risk_result_combined.json"))


def test_plan_without_risk_result_recomputes_it():
    p = crisis_plan(load("portfolio.json"), load("market_snapshot.json"), load("scenario_request.json"))
    assert p["positions"] == plan("")["positions"]
