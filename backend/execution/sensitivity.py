"""backend/execution/sensitivity.py — P3 : données de sensibilité pour le curseur du dashboard (P4).

Pour une position :
  1. J(x) en fonction de la probabilité p (0 → 50 %), pour chaque fraction de sortie x ;
  2. le seuil de bascule p*(x) quand la profondeur de la venue est divisée par 1, 2, 5, 10.

Les probabilités sont des hypothèses de l'utilisateur, jamais des estimations (section 7.4).
"""
import copy
from decimal import Decimal as D

from .decision import decide_position, ratio
from .exit_cost import DEFAULT_ESTIMATOR

ASSUMPTION_WARNING = "Assumption-driven: probabilities are user inputs, not estimates of the incident likelihood."


def sensitivity(portfolio, snapshot, risk_result, scenario_request, position_id,
                p_max="0.50", p_step="0.01", depth_divisors=("1", "2", "5", "10"), estimator=DEFAULT_ESTIMATOR):
    def run(snap, probability):
        request = copy.deepcopy(scenario_request)
        request["assumptions"]["probability"] = probability
        return decide_position(portfolio, snap, risk_result, request, position_id, estimator)

    # 1. J(x) en fonction de p : on rappelle le moteur à chaque p (mêmes arrondis que objective_usd).
    probabilities = []
    p = D(0)
    while p <= D(p_max):
        probabilities.append(p)
        p += D(p_step)
    runs = [run(snapshot, str(p)) for p in probabilities]
    fractions = [o["exit_fraction"] for o in runs[0]["exit_options"]]
    objective = {x: [next(o["objective_usd"] for o in r["exit_options"] if o["exit_fraction"] == x) for r in runs]
                 for x in fractions}

    # 2. p*(x) quand la venue de sortie est divisée en profondeur (pool plus mince = plus de slippage).
    venue_id = next(pos["exit_venue_id"] for pos in portfolio["positions"] if pos["position_id"] == position_id)
    venue = snapshot["exit_venues"].get(venue_id) or {}
    base_depth = venue.get("effective_depth_usd")
    depth_rows = []
    for divisor in depth_divisors:
        snap = copy.deepcopy(snapshot)
        depth = None
        if base_depth is not None:
            depth = D(base_depth) / D(divisor)
            snap["exit_venues"][venue_id]["effective_depth_usd"] = str(depth)
        out = run(snap, None)
        depth_rows.append({
            "depth_divisor": divisor,
            "effective_depth_usd": str(depth.quantize(D("0.01"))) if depth is not None else None,
            "break_even_probability": {o["exit_fraction"]: o["break_even_probability"]
                                       for o in out["exit_options"] if o["exit_fraction"] != "0.00"},
        })

    base = run(snapshot, None)
    warnings = [ASSUMPTION_WARNING] + base["warnings"]
    if base_depth is None:
        warnings.append(f"No effective depth for {venue_id}: depth sensitivity unavailable.")
    if any(o["quote_status"] != "proxy" for o in base["exit_options"]):
        warnings.append("Depth divisors only move the proxy; executable or pool quotes are not rescaled.")

    return {
        "position_id": position_id,
        "simulation_id": base["simulation_id"],
        "scenario_id": base["scenario_id"],
        "horizon_days": base["horizon_days"],
        "objective_vs_probability": {
            "probabilities": [ratio(p) for p in probabilities],
            "objective_usd": objective,
            "best_exit_fraction": [r["recommended_exit_fraction"] for r in runs],
        },
        "break_even_vs_depth": depth_rows,
        "warnings": warnings,
    }
