"""Scenario A: USDe market depeg (blueprint section 7.1).

Three distinct mechanisms, never reused as one multiplier:
- usde_spot_shock_pct: market price move (seen by oracles according to their pass-through);
- backing_impairment_pct: USDe backing loss (repriced by the market; an exchange-rate
  oracle with USDe hardcoded at 1 USD does not see it);
- susde_rate_cut_pct: loss socialised to stakers (every sUSDe oracle reads the rate).
"""

from __future__ import annotations

from backend.risk.metrics import read_metric
from backend.risk.model import Portfolio, Position, PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.pricing import MarketState, asset_price, oracle_price, position_values
from backend.risk.scenarios import scenario


@scenario("usde_depeg")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    shock = request.param("usde_spot_shock_pct", 0.0)
    beta = request.param("susde_market_beta", 1.0)
    impairment = request.param("backing_impairment_pct", 0.0)
    rate_cut = request.param("susde_rate_cut_pct", 0.0)
    apy_shift = request.param("pt_implied_apy_shock", 0.0)
    lag_hours = request.param("oracle_lag_hours", 0.0)

    before = MarketState.from_snapshot(snapshot)
    states = {
        "before": before,
        "market_only": before.shocked(shock, beta, 0.0, apy_shift),  # depeg alone
        "no_rate_cut": before.shocked(shock, beta, impairment, apy_shift),  # what market-price oracles see
        "after": before.shocked(shock, beta, impairment, apy_shift, susde_rate_cut=rate_cut),
    }

    outcome = ScenarioOutcome(impacts=[])
    for position in portfolio.positions:
        outcome.impacts.append(_impact(position, snapshot, states, rate_cut, request))
    if lag_hours and any(i.risk_metric and i.risk_metric["liquidatable"] for i in outcome.impacts):
        outcome.warnings.append(
            f"Oracle lag of {lag_hours:g}h: liquidatable positions can still be deleveraged before the oracle updates "
            "(see risk analytics: avoidable liquidation penalty)."
        )
    return outcome


def _impact(position: Position, snapshot: Snapshot, states: dict[str, MarketState], rate_cut: float,
            request: ScenarioRequest) -> PositionImpact:
    gross0, debt0 = position_values(position, states["before"], snapshot)
    gross_m, debt_m = position_values(position, states["market_only"], snapshot)
    gross1, debt1 = position_values(position, states["after"], snapshot)

    impact = PositionImpact(
        position_id=position.position_id,
        gross_before=gross0,
        gross_after=gross1,
        debt_after=debt1,
        net_before=gross0 - debt0,
        loss_components={
            "market_repricing": (gross0 - debt0) - (gross_m - debt_m),
            "backing_impairment": (gross_m - debt_m) - (gross1 - debt1),  # USDe impairment + sUSDe rate cut
            "liquidation_penalty": 0.0,
            "execution_haircut": 0.0,
        },
    )
    if position.position_type == "pt_holding":
        impact.warnings.append("PT valued with implied-APY discount approximation.")
    if position.is_borrow:
        _apply_liquidation_metric(impact, position, snapshot, states, rate_cut, request)
    return impact


def _apply_liquidation_metric(impact: PositionImpact, position: Position, snapshot: Snapshot,
                              states: dict[str, MarketState], rate_cut: float, request: ScenarioRequest) -> None:
    market = snapshot.market(position.position_id)
    if market is None:
        impact.insufficient_data = True
        impact.warnings.append("No market parameters: liquidation risk not computed.")
        return

    override = request.param("oracle_pass_through_override")
    if override is not None:
        pass_through = override
    elif "oracle_pass_through" in market:
        pass_through = float(market["oracle_pass_through"])
    else:
        pass_through = 1.0
        impact.warnings.append("Oracle pass-through unknown; assumed 1.0 (oracle follows market).")

    asset = position.collateral_asset
    price0 = asset_price(asset, states["before"], market)
    move = asset_price(asset, states["no_rate_cut"], market) / price0 - 1
    cut = rate_cut if asset == "sUSDe" else 0.0
    debt0 = position.debt_quantity * asset_price(position.debt_asset, states["before"], market)

    def reading(pt: float):
        collateral_after = position.collateral_quantity * oracle_price(price0, move, pt, cut)
        return collateral_after, read_metric(market, position.collateral_quantity * price0, collateral_after, debt0, impact.debt_after)

    oracle_collateral, metric = reading(pass_through)
    impact.risk_metric = {
        "type": metric.type,
        "before": metric.before,
        "after": metric.after,
        "threshold": metric.threshold,
        "liquidatable": metric.liquidatable,
        "distance_to_liquidation_before_pct": metric.distance_before,
        "distance_to_liquidation_after_pct": metric.distance_after,
    }
    impact.internals = {"market": market, "oracle_collateral_after": oracle_collateral, "metric": metric}

    if metric.liquidatable:
        # Liquidators repay close_factor x debt and seize that amount plus the incentive.
        repaid = metric.close_factor * impact.debt_after
        impact.loss_components["liquidation_penalty"] = repaid * metric.liquidation_incentive
        impact.warnings.append(
            f"Liquidatable: liquidators may repay {metric.close_factor:.0%} of the debt; penalty = repaid debt x incentive."
        )
    if not market.get("verified"):
        impact.warnings.append("Liquidation parameters and oracle response are fixture assumptions.")
    if pass_through < 1:
        _, alt = reading(1.0)
        impact.warnings.append(
            f"Oracle assumed to pass through {pass_through:g} of the market move; if it fully follows the market, "
            f"{alt.type} becomes {alt.after:.4f} (liquidatable: {alt.liquidatable})."
        )
