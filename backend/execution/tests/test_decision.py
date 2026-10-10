import copy
import json
from decimal import Decimal as D

import pytest

from backend.execution.decision import FIXTURE_DIR, decide_portfolio, decide_position, load_contracts


@pytest.fixture
def contracts():
    return load_contracts()


def run(c, position_id="aave_01"):
    return decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], position_id)


def test_aave_01_matches_golden_fixture_field_by_field(contracts):
    golden = json.loads((FIXTURE_DIR / "decision_result.json").read_text())
    got = run(contracts)
    assert list(got) == list(golden)                       # mêmes champs, même ordre
    for key in golden:
        assert got[key] == golden[key], key


def test_inconsistent_request_ids_are_rejected(contracts):
    c = copy.deepcopy(contracts)
    c["risk_result"]["request_id"] = "sim_999"
    with pytest.raises(ValueError, match="request_id"):
        run(c)


def test_unknown_position_is_rejected(contracts):
    with pytest.raises(ValueError, match="nope_01"):
        run(contracts, "nope_01")


def run_portfolio(c):
    return decide_portfolio(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"])


def test_all_four_positions_get_five_options(contracts):
    out = run_portfolio(contracts)
    assert [d["position_id"] for d in out["decisions"]] == ["ethena_susde_01", "aave_01", "morpho_01", "pendle_01"]
    for d in out["decisions"]:
        assert [o["exit_fraction"] for o in d["exit_options"]] == ["0.00", "0.25", "0.50", "0.75", "1.00"]


def test_borrow_position_sells_collateral_not_net_equity(contracts):
    # aave_01 : 25 % = 750 000 $ de garantie vendue → frais 0,1 % = 750 $ (et pas 25 % × 1,2 M$ de valeur nette)
    o = run(contracts)["exit_options"][1]
    assert o["fees_usd"] == "750.00"


def test_summary_stay_loss_matches_risk_result_total(contracts):
    summary = run_portfolio(contracts)["summary"]
    assert summary["stay_conditional_loss_usd"] == contracts["risk_result"]["portfolio"]["total_conditional_loss_usd"]
    assert summary["chosen_actions"] is None                # probabilité null → aucun choix à additionner


def test_summary_adds_chosen_actions_and_flags_shared_venue(contracts):
    c = copy.deepcopy(contracts)
    c["scenario_request"]["assumptions"]["probability"] = "0.10"
    out = run_portfolio(c)
    chosen_cost = sum(D(o["estimated_exit_cost_usd"]) for d in out["decisions"] for o in d["exit_options"]
                      if o["exit_fraction"] == d["recommended_exit_fraction"])
    assert D(out["summary"]["chosen_actions"]["estimated_exit_cost_usd"]) == chosen_cost
    assert any("venue:susde_usdc" in w for w in out["summary"]["warnings"])


# --- Étape 5 : règles de recommandation (section 8) ---

def with_probability(c, p):
    c = copy.deepcopy(c)
    c["scenario_request"]["assumptions"]["probability"] = p
    return c


def test_probability_with_proxy_quotes_recommends_but_flags(contracts):
    out = run(with_probability(contracts, "0.15"))
    assert (out["mode"], out["recommendation"], out["recommended_exit_fraction"]) == ("expected_cost", "REDUCE", "0.25")
    assert all(o["objective_usd"] is not None for o in out["exit_options"])
    assert any(w.startswith("proxy_quotes") for w in out["warnings"])


def test_probability_outside_0_1_is_rejected(contracts):
    with pytest.raises(ValueError, match="probability"):
        run(with_probability(contracts, "1.5"))


def test_reason_names_the_cheapest_threshold_not_always_25pct(contracts):
    # Pool quasi infinie + gas énorme : le coût fixe domine, la sortie totale devient rentable la première.
    c = copy.deepcopy(contracts)
    c["snapshot"]["exit_venues"]["venue:usde_usdc"].update(effective_depth_usd="1000000000000", gas_usd="5000")
    out = run(c)
    p_stars = {o["exit_fraction"]: D(o["break_even_probability"]) for o in out["exit_options"][1:]}
    assert min(p_stars, key=p_stars.get) == "1.00"
    assert "Exiting fully beats staying" in out["reason"]


def test_liquidity_crisis_exits_at_pre_crisis_depth(contracts):
    liq = load_contracts(liquidity=True)
    out = run(liq)
    assert (out["decision_id"], out["simulation_id"], out["scenario_id"]) == ("decision_sim_002", "result_sim_002", "liquidity_crisis")
    # Mêmes coûts qu'avant la crise (profondeur 300 M$, pas 60 M$) ; seule la perte change (142 857,14 $).
    depeg_costs = [o["estimated_exit_cost_usd"] for o in run(contracts)["exit_options"]]
    assert [o["estimated_exit_cost_usd"] for o in out["exit_options"]] == depeg_costs
    assert out["exit_options"][1]["break_even_probability"] == "0.0813"
    assert "liquidity crisis exceeds 8.13%" in out["reason"]
