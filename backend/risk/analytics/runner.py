"""Run scenarios in-process with parameter overrides (no JSON round trip), for analytics loops."""

from __future__ import annotations

from dataclasses import replace

from backend.risk import scenarios
from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot

NEUTRAL_DEPEG = {
    "usde_spot_shock_pct": 0.0,
    "susde_market_beta": 1.0,
    "backing_impairment_pct": 0.0,
    "susde_rate_cut_pct": 0.0,
    "oracle_pass_through_override": None,
    "oracle_lag_hours": 0.0,
    "pt_pricing_mode": "implied_apy_discount",
    "pt_implied_apy_shock": 0.0,
}


def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, **overrides) -> ScenarioOutcome:
    params = {**request.parameters, **overrides}
    return scenarios.get(request.scenario_id)(portfolio, snapshot, replace(request, parameters=params))


def neutral_depeg(request: ScenarioRequest) -> ScenarioRequest:
    """A no-shock depeg request on the same portfolio/snapshot, used to probe single risk factors."""
    keep = {}
    if request.scenario_id in ("usde_depeg", "combined_crisis", "node_shock"):
        # Keep the user's structural assumptions (sUSDe beta, oracle override), drop the shocks.
        keep = {k: request.parameters[k] for k in ("susde_market_beta", "oracle_pass_through_override") if k in request.parameters}
    return replace(request, scenario_id="usde_depeg", parameters={**NEUTRAL_DEPEG, **keep})


def position_loss(outcome: ScenarioOutcome, position_id: str) -> float:
    impact = next(i for i in outcome.impacts if i.position_id == position_id)
    return sum(impact.loss_components.values())


def total_loss(outcome: ScenarioOutcome) -> float:
    return sum(sum(i.loss_components.values()) for i in outcome.impacts) + outcome.shared_liquidity_penalty
