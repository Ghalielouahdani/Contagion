"""Provisional decision_result, computed from the risk engine until P3's execution module lands.

Applies blueprint section 8 to one position: for exit fractions 0/25/50/75/100%, exit cost
(fees + gas + price impact at normal depth), foregone yield over the horizon, residual
stress loss and break-even probability. It reproduces the demo decision fixture exactly.
Clearly labelled provisional in its warnings; P3 replaces it behind the same endpoint.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from backend.risk import scenarios
from backend.risk.analytics.derisking import build_legs, cost_parts
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
QUOTE_STATUS = {"executable_quote": "executable", "pool_reserves": "pool_reserves", "proxy": "proxy"}


def _money(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _ratio(x: float) -> str:
    return str(Decimal(repr(float(x))).quantize(Decimal("0.0001"), ROUND_HALF_UP))


def decide(portfolio: dict, snapshot: dict, request: dict, position_id: str) -> dict:
    p, s, r = Portfolio.from_contract(portfolio), Snapshot.from_contract(snapshot), ScenarioRequest.from_contract(request)
    outcome = scenarios.get(r.scenario_id)(p, s, r)
    legs = {leg.position_id: leg for leg in build_legs(p, s, outcome, r.horizon_days)}
    if position_id not in legs:
        raise KeyError(f"unknown position_id {position_id!r}")
    leg = legs[position_id]
    venue = s.venues.get(leg.venue_id) if leg.venue_id else None
    quote_status = QUOTE_STATUS.get(venue.quote_method, "proxy") if venue else "unavailable"
    loss = _money(leg.stress_loss_usd)

    options = []
    for x in FRACTIONS:
        parts = cost_parts({position_id: x}, [leg], s)
        fees, gas, impact = (_money(parts[k]) for k in ("fees_usd", "gas_usd", "price_impact_usd"))
        cost = fees + gas + impact
        foregone = _money(parts["foregone_yield_usd"])
        residual = _money((1 - x) * leg.stress_loss_usd)
        protected = loss - residual
        options.append({
            "exit_fraction": f"{x:.2f}",
            "fees_usd": str(fees),
            "gas_usd": str(gas),
            "price_impact_usd": str(impact),
            "estimated_exit_cost_usd": str(cost),
            "foregone_yield_usd": str(foregone),
            "residual_stress_loss_usd": str(residual),
            "break_even_probability": _ratio((cost + foregone) / protected) if x > 0 and protected > 0 else None,
            "objective_usd": (str(_money(float(cost) + r.probability * float(residual) + float(foregone)))
                              if r.probability is not None else None),
            "quote_status": quote_status,
        })

    warnings = ["Provisional: computed by the risk engine (blueprint section 8) until the P3 execution module is connected."]
    if quote_status != "executable":
        warnings.append(f"Exit costs use {quote_status} quotes on {leg.venue_id}; replace with executable quotes.")

    if r.probability is None:
        recommendation, fraction, mode = "INSUFFICIENT_DATA", None, "conditional_stress"
        first = next((o for o in options if o["break_even_probability"] is not None), None)
        reason = "No scenario probability supplied: compare costs with protection instead of trusting an optimal trade."
        if first:
            reason += (f" Exiting {float(first['exit_fraction']):.0%} beats staying if the probability of this scenario over "
                       f"{r.horizon_days} days exceeds {float(first['break_even_probability']):.2%}.")
    else:
        mode = "expected_cost"
        best = min(options, key=lambda o: Decimal(o["objective_usd"]))
        fraction = best["exit_fraction"]
        recommendation = "STAY" if fraction == "0.00" else "EXIT" if fraction == "1.00" else "REDUCE"
        reason = (f"With a {r.probability:.2%} scenario probability, exiting {float(fraction):.0%} minimises "
                  f"exit cost + expected residual loss + foregone yield ({best['objective_usd']} USD).")
        if quote_status == "proxy":
            warnings.append("Recommendation relies on proxy quotes (flag: proxy_quotes).")

    return {
        "schema_version": "1.0",
        "decision_id": f"decision_{r.request_id}",
        "simulation_id": f"result_{r.request_id}",
        "portfolio_id": r.portfolio_id,
        "position_id": position_id,
        "scenario_id": r.scenario_id,
        "horizon_days": r.horizon_days,
        "mode": mode,
        "currency": "USD",
        "exit_options": options,
        "recommendation": recommendation,
        "recommended_exit_fraction": fraction,
        "reason": reason,
        "warnings": warnings,
    }
