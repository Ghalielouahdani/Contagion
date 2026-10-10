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
