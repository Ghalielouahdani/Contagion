"""Scenario G: liquidation cascade (roadmap step 4). The depeg feeds itself through forced selling.

The initial USDe shock (scenario A parameters) starts the cascade in cascade.py; the scenario then
prices the portfolio at the cascade's final market moves:
- borrow, holding and PT positions: scenario A at the final USDe move, with the sUSDe move expressed
  as an effective beta (each asset moves on its own venue);
- lender positions: bad debt and underwater debt counted round by round by the cascade (bad debt at
  the price of the round it was liquidated in), not recomputed at the final price.
The comparison block reports the same initial shock without feedback: the excess is the loss the
cascade adds. The result carries a `cascade` block (rounds, amplification, stuck debt).
"""

from __future__ import annotations

from dataclasses import replace

from backend.risk import cascade
from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.scenarios import scenario, usde_depeg


@scenario("liquidation_cascade")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    shock = request.param("usde_spot_shock_pct", 0.0)
    beta = request.param("susde_market_beta", 1.0)
    reduction = request.param("exit_liquidity_reduction_pct", 0.0)
    initial = {"USDe": shock, "sUSDe": beta * shock}

    impact_aware = bool(request.parameters.get("liquidators_internalize_impact", False))
    absorption = request.param("arbitrage_absorption_pct", 0.0)
    result = cascade.run(portfolio, snapshot, initial, 1 - reduction, request.param("oracle_pass_through_override"),
                         impact_aware, absorption)
    final_usde, final_susde = result.moves["USDe"], result.moves["sUSDe"]
    final = replace(request, parameters={
        **request.parameters,
        "usde_spot_shock_pct": final_usde,
        "susde_market_beta": final_susde / final_usde if final_usde else beta,
    })
    outcome = usde_depeg.run(portfolio, snapshot, final)
    for impact in outcome.impacts:
        losses = cascade.lender_losses(result, portfolio, snapshot).get(impact.position_id)
        if losses is None or "lender" not in impact.internals:
            continue
        old = impact.loss_components["bad_debt"] + impact.loss_components["undercollateralized_debt"]
        impact.loss_components["bad_debt"], impact.loss_components["undercollateralized_debt"] = losses
        impact.gross_after += old - sum(losses)
        impact.warnings.append("Lender loss counted round by round in the cascade (bad debt at liquidation-time prices).")

    without = usde_depeg.run(portfolio, snapshot, request)
    outcome.comparison = {
        "runs": [{"run_id": "initial_shock_only", "description": "Same initial shock, no liquidation feedback.",
                  "total_loss": sum(sum(i.loss_components.values()) for i in without.impacts)}],
        "excess_meaning": "Loss added by the cascade: forced selling pushes prices further and triggers new liquidations.",
    }
    outcome.cascade = _summary(result)
    outcome.warnings.extend(result.warnings)
    outcome.warnings.append(
        "Cascade model: liquidators " + ("stop when their own selling eats the incentive" if impact_aware else
        "are price takers (liquidate whenever profitable at the current price: worst case)") + "; one exit "
        "venue per collateral, no USDe/sUSDe arbitrage, borrower distribution as given in the snapshot.")
    return outcome


def _summary(result: cascade.CascadeResult) -> dict:
    initial, final = result.initial_moves["USDe"], result.moves["USDe"]
    return {
        "initial_moves": result.initial_moves,
        "final_moves": result.moves,
        "trough_moves": result.troughs,
        "amplification": final / initial if initial else None,
        "rounds": result.rounds,
        "liquidated_debt": sum(b.liquidated for b in result.buckets),
        "bad_debt": sum(b.bad_debt for b in result.buckets if b.origin == "market"),
        "stuck_debt": sum(b.remaining for b in result.buckets if b.stuck),
        "converged": result.converged,
    }
