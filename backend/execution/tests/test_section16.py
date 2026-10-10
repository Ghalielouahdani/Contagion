"""Tests exigés par la section 16 P3 (et la ligne Decision de la section 12) du blueprint."""
import copy
from decimal import Decimal as D

import pytest

from backend.execution.decision import decide_position, load_contracts

POSITIONS = ["ethena_susde_01", "aave_01", "morpho_01", "pendle_01"]


@pytest.fixture
def contracts():
    return load_contracts()


def run(c, position_id="aave_01", probability=None, depth_factor=None, loss=None):
    c = copy.deepcopy(c)
    c["scenario_request"]["assumptions"]["probability"] = probability
    if depth_factor is not None:            # profondeur × facteur pour toutes les venues
        for venue in c["snapshot"]["exit_venues"].values():
            venue["effective_depth_usd"] = str(D(venue["effective_depth_usd"]) * D(depth_factor))
    if loss is not None:
        next(p for p in c["risk_result"]["positions"] if p["position_id"] == position_id)["conditional_loss_usd"] = loss
    return decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], position_id)


def by_fraction(out, field):
    return {o["exit_fraction"]: D(o[field]) for o in out["exit_options"]}


@pytest.mark.parametrize("position_id", POSITIONS)
def test_zero_exit_costs_nothing(contracts, position_id):
    stay = run(contracts, position_id)["exit_options"][0]
    assert stay["exit_fraction"] == "0.00"
    assert [stay[k] for k in ("fees_usd", "gas_usd", "price_impact_usd", "estimated_exit_cost_usd",
                              "foregone_yield_usd")] == ["0"] * 5


@pytest.mark.parametrize("position_id", POSITIONS)
def test_exit_cost_is_convex_in_size(contracts, position_id):
    out = run(contracts, position_id)
    impact = by_fraction(out, "price_impact_usd")
    # Vendre 2× plus coûte plus de 2× plus en impact de prix…
    assert impact["0.50"] > 2 * impact["0.25"] and impact["1.00"] > 2 * impact["0.50"]
    # … et chaque tranche de 25 % coûte plus que la précédente.
    cost = [by_fraction(out, "estimated_exit_cost_usd")[x] for x in ("0.00", "0.25", "0.50", "0.75", "1.00")]
    steps = [b - a for a, b in zip(cost, cost[1:])]
    assert steps == sorted(steps) and len(set(steps)) == 4


def test_full_exit_leaves_no_residual_loss(contracts):
    out = run(contracts, probability="0.40")
    full = out["exit_options"][-1]
    assert (full["exit_fraction"], full["residual_stress_loss_usd"]) == ("1.00", "0")
    assert (out["recommendation"], out["recommended_exit_fraction"]) == ("EXIT", "1.00")


def test_no_incident_means_stay(contracts):
    out = run(contracts, probability="0.10", loss="0")
    assert (out["recommendation"], out["recommended_exit_fraction"]) == ("STAY", "0.00")
    assert all(o["break_even_probability"] is None for o in out["exit_options"])
    # Sans probabilité, la règle 1 impose INSUFFICIENT_DATA, mais le texte dit que rien ne bat STAY.
    assert "no exit can beat staying" in run(contracts, loss="0")["reason"]


@pytest.mark.parametrize("position_id", POSITIONS)
def test_higher_probability_never_lowers_the_exit(contracts, position_id):
    chosen = [D(run(contracts, position_id, probability=str(D(p) / 100))["recommended_exit_fraction"])
              for p in range(0, 101, 2)]
    assert chosen == sorted(chosen)
    assert chosen[0] == 0 and chosen[-1] == 1           # p = 0 → STAY ; p = 1 → EXIT


@pytest.mark.parametrize("position_id", POSITIONS)
def test_more_slippage_never_raises_the_exit(contracts, position_id):
    factors = ["10", "5", "2", "1", "0.5", "0.2", "0.1"]      # pool de plus en plus mince
    chosen = [D(run(contracts, position_id, probability="0.20", depth_factor=f)["recommended_exit_fraction"])
              for f in factors]
    assert chosen == sorted(chosen, reverse=True)
    assert chosen[0] > chosen[-1]                              # la profondeur change vraiment le choix


def test_partial_exit_can_win(contracts):
    out = run(contracts, probability="0.15")
    j = by_fraction(out, "objective_usd")
    assert (out["recommendation"], out["recommended_exit_fraction"]) == ("REDUCE", "0.25")
    assert j["0.25"] < j["0.00"] and j["0.25"] < j["1.00"]     # mieux que garder ET que tout vendre


def test_golden_values_section_11_8(contracts):
    out = run(contracts)
    got = [(o["exit_fraction"], o["estimated_exit_cost_usd"], o["foregone_yield_usd"], o["break_even_probability"])
           for o in out["exit_options"]]
    assert got == [
        ("0.00", "0", "0", None),
        ("0.25", "2660.32", "244.52", "0.0775"),
        ("0.50", "9002.69", "489.04", "0.1266"),
        ("0.75", "19039.38", "733.56", "0.1758"),
        ("1.00", "32742.97", "978.08", "0.2248"),
    ]
    assert (out["mode"], out["recommendation"], out["recommended_exit_fraction"]) == ("conditional_stress", "INSUFFICIENT_DATA", None)
    assert all(o["objective_usd"] is None for o in out["exit_options"])
