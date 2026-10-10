import copy
import json
from decimal import Decimal as D

import pytest

from backend.execution.decision import decide_position, load_contracts
from backend.execution.sensitivity import sensitivity


@pytest.fixture
def contracts():
    return load_contracts()


def run(c, position_id="aave_01", **kwargs):
    return sensitivity(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], position_id, **kwargs)


def test_objective_curve_covers_0_to_50pct_for_every_option(contracts):
    curve = run(contracts)["objective_vs_probability"]
    assert curve["probabilities"][0] == "0.0000" and curve["probabilities"][-1] == "0.5000"
    assert len(curve["probabilities"]) == 51
    assert list(curve["objective_usd"]) == ["0.00", "0.25", "0.50", "0.75", "1.00"]
    assert all(len(v) == 51 for v in curve["objective_usd"].values())


def test_objective_at_p0_is_the_certain_cost_and_full_exit_is_flat(contracts):
    j = run(contracts)["objective_vs_probability"]["objective_usd"]
    assert j["0.25"][0] == "2904.84"                        # 2660.32 de sortie + 244.52 de rendement perdu
    assert set(j["1.00"]) == {"33721.05"}                  # plus rien d'exposé : J ne dépend plus de p


def test_best_fraction_matches_the_engine_and_never_decreases(contracts):
    curve = run(contracts)["objective_vs_probability"]
    i = curve["probabilities"].index("0.1500")
    assert curve["best_exit_fraction"][i] == "0.25"
    best = [D(x) for x in curve["best_exit_fraction"]]
    assert best == sorted(best)


def test_break_even_rises_as_depth_is_divided(contracts):
    rows = run(contracts)["break_even_vs_depth"]
    assert [r["depth_divisor"] for r in rows] == ["1", "2", "5", "10"]
    assert rows[0]["break_even_probability"]["0.25"] == "0.0775"           # profondeur normale = golden 11.8
    assert rows[3]["effective_depth_usd"] == "30000000.00"
    for x in ["0.25", "0.50", "0.75", "1.00"]:
        p_stars = [D(r["break_even_probability"][x]) for r in rows]
        assert p_stars == sorted(p_stars) and len(set(p_stars)) == 4


def test_missing_depth_gives_null_thresholds_and_a_warning(contracts):
    c = copy.deepcopy(contracts)
    c["snapshot"]["exit_venues"]["venue:usde_usdc"]["effective_depth_usd"] = None
    out = run(c)
    assert all(r["break_even_probability"] == {} for r in out["break_even_vs_depth"])
    assert any("depth sensitivity unavailable" in w for w in out["warnings"])
    assert out["objective_vs_probability"]["best_exit_fraction"][-1] is None   # pas de prix → pas de choix


def test_output_is_plain_json_with_string_numbers(contracts):
    out = run(contracts)
    assert json.loads(json.dumps(out)) == out
    assert out["warnings"][0].startswith("Assumption-driven")


def test_reason_says_no_exit_pays_when_every_p_star_exceeds_100pct(contracts):
    c = copy.deepcopy(contracts)
    c["snapshot"]["exit_venues"]["venue:usde_usdc"]["effective_depth_usd"] = "1000000"   # pool minuscule
    out = decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], "aave_01")
    assert all(D(o["break_even_probability"]) > 1 for o in out["exit_options"][1:])
    assert "no exit can beat staying even if this depeg is certain" in out["reason"]
