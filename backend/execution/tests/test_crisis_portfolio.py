import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.execution.crisis import CrisisModel, crisis_plan
from backend.execution.hedging import hedge_universe, shocked_assets

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01"
SCENARIOS = ["", "_liquidity", "_combined", "_carry", "_governance", "_node_shock", "_cascade", "_severe"]


def load(name):
    return json.loads((FIXTURES / name).read_text())


def inputs(suffix=""):
    return load("portfolio.json"), load("market_snapshot.json"), load(f"scenario_request{suffix}.json"), \
        load(f"risk_result{suffix}.json")


def strategies(suffix="", timing="early", **kwargs):
    return {s["strategy_id"]: s for s in crisis_plan(*inputs(suffix), include_strategies=True, **kwargs)["strategies"][timing]}


def flat_quotes(asset, stable):   # fausse cotation à la demande (pas de réseau dans les tests)
    return {"asset": asset, "quote_method": "executable_quote", "effective_depth_usd": "50000000", "fee_rate": "0",
            "gas_usd": "90", "quotes": [{"size_usd": "500000", "loss_pct": "0.05"}, {"size_usd": "5000000", "loss_pct": "0.10"}]}


def test_keeping_everything_costs_the_scenario_loss():
    # Dépeg sans coût de sortie forcée : garder tout = la perte publiée par P2.
    _, _, _, risk = inputs("")
    assert strategies("")["hold_all"]["total_loss_usd"] == risk["portfolio"]["total_conditional_loss_usd"]


def test_selling_on_a_shared_venue_is_priced_jointly():
    model = CrisisModel(*inputs("_combined"))
    pids = ("ethena_susde_01", "morpho_01")
    together = model.evaluate("early", {pid: ("sell", "1.00") for pid in pids})
    impact_together = sum(D(p["price_impact_usd"]) for p in together["positions"] if p["position_id"] in pids)
    impact_alone = sum(model.option(pid, "early", "sell", "1.00")["impact"] for pid in pids)
    penalty = D(together["shared_venue_penalty_usd"])
    assert penalty > 0                                                     # vendre ensemble coûte plus cher
    assert impact_together - impact_alone == pytest.approx(penalty, abs=D("0.02"))


@pytest.mark.parametrize("suffix", SCENARIOS)
@pytest.mark.parametrize("timing", ["early", "late"])
def test_min_loss_beats_every_other_computed_strategy(suffix, timing):
    found = strategies(suffix, timing)
    best = D(found["min_loss"]["total_loss_usd"])
    assert all(best <= D(s["total_loss_usd"]) for s in found.values())


def test_shared_venue_makes_min_loss_sell_less_than_alone():
    # Seules, Ethena et Morpho seraient vendues à 100 % ; vendre les deux dans la même pool sUSDe coûte trop cher,
    # donc la stratégie coordonnée vend moins sur cette venue (laquelle garder dépend des chiffres) et perd moins.
    portfolio, snapshot, request, risk = inputs("_combined")
    shared = [p["position_id"] for p in portfolio["positions"] if p["exit_venue_id"] == "venue:susde_usdc"]
    alone = {r["position_id"]: r["early"]["best"] for r in crisis_plan(portfolio, snapshot, request, risk)["positions"]}
    assert all(alone[pid]["action"] == "sell" and alone[pid]["fraction"] == "1.00" for pid in shared)
    plan = strategies("_combined")["min_loss"]
    sold_fraction = lambda choice: D(choice["fraction"]) if choice["action"] == "sell" else D(0)  # noqa: E731
    assert sum(sold_fraction(plan["choices"][pid]) for pid in shared) < len(shared)
    model = CrisisModel(portfolio, snapshot, request, risk)
    naive = {pid: (best["action"], best["fraction"]) for pid, best in alone.items()}
    assert D(plan["total_loss_usd"]) < model.evaluate("early", naive)["_total"]


def test_identical_strategies_are_flagged():
    late = strategies("_carry", "late")
    assert late["protect_liquidations"]["same_as"] == "min_loss"


def test_late_exit_all_never_withdraws_lenders():
    choices = strategies("_cascade", "late")["exit_all"]["choices"]
    assert not any(c["action"] == "withdraw" for c in choices.values())


def test_unknown_option_is_rejected():
    with pytest.raises(ValueError, match="No"):
        CrisisModel(*inputs("")).evaluate("late", {"lend_susde_01": ("withdraw", "1.00")})


# --- Univers de couverture ---

def test_shocked_assets_follow_the_scenario():
    assert set(shocked_assets(load("scenario_request.json"))) == {"USDe", "sUSDe", "PT-sUSDe"}
    assert shocked_assets(load("scenario_request_carry.json")) == {}
    request = copy.deepcopy(load("scenario_request_node_shock.json"))
    request["scenario"]["parameters"]["node_id"] = "asset:PYUSD"
    assert set(shocked_assets(request)) == {"PYUSD"}


def test_offline_universe_only_prices_the_snapshot_usdc_route():
    universe = hedge_universe(load("market_snapshot.json"), load("scenario_request.json"))
    usable = {a["asset"] for a in universe["assets"] if a["usable_as_hedge"]}
    assert usable == {"USDC"}
    usdc = next(a for a in universe["assets"] if a["asset"] == "USDC")
    assert {r["from"]: r["status"] for r in usdc["routes"]}["PT-sUSDe"] == "unavailable"
    assert len(universe["unpriced_instruments"]) == 3   # short perps, options, assurance : jamais chiffrés


def test_rotation_into_an_unshocked_stablecoin_with_on_demand_quotes():
    found = strategies("", quote_source=flat_quotes)
    rotation = found["rotate_into_pyusd"]
    assert "rotate_into_usdc" not in found                    # USDC = exit_all, pas répété
    assert rotation["unpriced_positions"] == ["pendle_01"]    # PT absent du registre : gardé, pas inventé
    assert "pendle_01" not in rotation["choices"]


def test_no_rotation_into_the_shocked_stablecoin():
    portfolio, snapshot, request, _ = inputs("_node_shock")
    request = copy.deepcopy(request)
    request["scenario"]["parameters"]["node_id"] = "asset:PYUSD"
    plan = crisis_plan(portfolio, snapshot, request, include_strategies=True, quote_source=flat_quotes)
    ids = {s["strategy_id"] for s in plan["strategies"]["early"]}
    assert "rotate_into_pyusd" not in ids                     # PYUSD est le nœud choqué : ce n'est plus une couverture
    assert next(a for a in plan["hedging"]["assets"] if a["asset"] == "PYUSD")["shocked_in_scenario"]
