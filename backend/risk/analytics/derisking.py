"""Targeted vs uniform de-risking: the same protection for less money.

A PM who wants to halve the stress loss without this tool cuts every position by the same
share ("uniform"). The engine knows which positions carry the loss and what each exit
costs (fees, gas, price impact on a possibly shared venue, foregone yield), so it buys the
same protection where it is cheapest ("targeted"). The difference is money the fund keeps.

Exits happen before the scenario, at normal (pre-crisis) depth; pro-rata exits keep
LTV/HF unchanged, so a position's residual stress loss scales with (1 - fraction).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.risk.liquidity import haircut
from backend.risk.model import Portfolio, ScenarioOutcome, Snapshot

STEP = 0.05


@dataclass(frozen=True)
class Leg:
    position_id: str
    venue_id: str | None
    size_usd: float  # value sold at a full exit (collateral for a borrow)
    stress_loss_usd: float  # conditional loss of the position in the scenario
    carry_usd: float  # net yield earned over the horizon if the position is kept


def build_legs(portfolio: Portfolio, snapshot: Snapshot, outcome: ScenarioOutcome, horizon_days: int) -> list[Leg]:
    impacts = {i.position_id: i for i in outcome.impacts}
    legs = []
    for p in portfolio.positions:
        y = snapshot.yields.get(p.position_id, {})
        if p.is_borrow:
            annual = y.get("collateral_supply_apy", 0.0) * p.gross_value_usd - y.get("debt_borrow_apy", 0.0) * p.debt_value_usd
        else:
            annual = y.get("token_apy", 0.0) * p.gross_value_usd
        venue = p.exit_venue_id if p.exit_venue_id in snapshot.venues else None
        legs.append(Leg(p.position_id, venue, p.gross_value_usd, sum(impacts[p.position_id].loss_components.values()),
                        annual * horizon_days / 365))
    return legs


def exit_costs(fractions: dict[str, float], legs: list[Leg], snapshot: Snapshot) -> dict[str, float]:
    """Trading cost (fees + gas + joint price impact per venue) and foregone yield of an exit plan."""
    parts = cost_parts(fractions, legs, snapshot)
    trading = parts["fees_usd"] + parts["gas_usd"] + parts["price_impact_usd"]
    return {"trading_cost_usd": trading, "foregone_yield_usd": parts["foregone_yield_usd"],
            "total_cost_usd": trading + parts["foregone_yield_usd"]}


def cost_parts(fractions: dict[str, float], legs: list[Leg], snapshot: Snapshot) -> dict[str, float]:
    """Fees, gas, joint price impact per venue and foregone yield of an exit plan, separately."""
    sold_by_venue: dict[str, float] = {}
    fees = gas = foregone = 0.0
    for leg in legs:
        x = fractions.get(leg.position_id, 0.0)
        if x <= 0:
            continue
        foregone += x * leg.carry_usd
        if leg.venue_id is None:
            continue
        venue = snapshot.venues[leg.venue_id]
        size = x * leg.size_usd
        sold_by_venue[leg.venue_id] = sold_by_venue.get(leg.venue_id, 0.0) + size
        fees += venue.fee_rate * size
        gas += venue.gas_usd
    impact = sum(haircut(size, snapshot.venues[v].effective_depth_usd) for v, size in sold_by_venue.items())
    return {"fees_usd": fees, "gas_usd": gas, "price_impact_usd": impact, "foregone_yield_usd": foregone}


def _plan(name: str, fractions: dict[str, float], legs: list[Leg], snapshot: Snapshot) -> dict:
    reduction = sum(fractions[l.position_id] * l.stress_loss_usd for l in legs)
    costs = exit_costs(fractions, legs, snapshot)
    return {
        "plan": name,
        "fractions": dict(fractions),
        "loss_reduction_usd": reduction,
        **costs,
        # Acting pays off if the scenario's probability over the horizon exceeds this.
        "break_even_probability": costs["total_cost_usd"] / reduction if reduction > 0 else None,
    }


def targeted_fractions(legs: list[Leg], snapshot: Snapshot, target_usd: float) -> dict[str, float]:
    """Greedy on marginal cost: each step buys the next 5% of protection where it is cheapest.

    Exit costs are convex (price impact grows with size, venues are shared), so cheapest-first
    is the natural allocation; the caller keeps the uniform plan if it is ever cheaper.
    """
    fractions = {l.position_id: 0.0 for l in legs}
    reduced = 0.0
    while reduced < target_usd - 1e-6:
        base_cost = exit_costs(fractions, legs, snapshot)["total_cost_usd"]
        best, best_score = None, None
        for leg in legs:
            x = fractions[leg.position_id]
            if x >= 1 - 1e-9 or leg.stress_loss_usd <= 0 or leg.venue_id is None:
                continue
            trial = {**fractions, leg.position_id: min(1.0, x + STEP)}
            delta_cost = exit_costs(trial, legs, snapshot)["total_cost_usd"] - base_cost
            delta_reduction = (trial[leg.position_id] - x) * leg.stress_loss_usd
            score = delta_reduction / delta_cost if delta_cost > 1e-9 else float("inf")
            if best_score is None or score > best_score:
                best, best_score = leg, score
        if best is None:
            break
        step = min(1.0, fractions[best.position_id] + STEP) - fractions[best.position_id]
        fractions[best.position_id] += step
        reduced += step * best.stress_loss_usd
    return fractions


def compare(legs: list[Leg], snapshot: Snapshot, nav: float, target_pct: float = 0.5) -> dict:
    total_loss = sum(l.stress_loss_usd for l in legs)
    uniform = _plan("uniform", {l.position_id: target_pct for l in legs}, legs, snapshot)
    targeted = _plan("targeted", targeted_fractions(legs, snapshot, target_pct * total_loss), legs, snapshot)
    if targeted["total_cost_usd"] >= uniform["total_cost_usd"]:
        targeted = {**uniform, "plan": "targeted"}
    panic = _plan("full_exit", {l.position_id: 1.0 for l in legs}, legs, snapshot)
    savings = uniform["total_cost_usd"] - targeted["total_cost_usd"]
    return {
        "target_loss_reduction_pct": target_pct,
        "stress_loss_usd": total_loss,
        "uniform": uniform,
        "targeted": targeted,
        "full_exit": panic,
        "savings_usd": savings,
        "savings_pct_of_uniform_cost": savings / uniform["total_cost_usd"] if uniform["total_cost_usd"] else 0.0,
        "savings_bps_nav": savings / nav * 1e4,
        "cost_per_usd_protected": {
            l.position_id: (exit_costs({l.position_id: 1.0}, legs, snapshot)["total_cost_usd"] / l.stress_loss_usd
                            if l.stress_loss_usd > 0 else None)
            for l in legs
        },
    }
