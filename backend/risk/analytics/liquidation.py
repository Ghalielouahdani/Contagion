"""Liquidation protection: spend a little now to avoid a liquidation penalty later.

For every position the scenario makes liquidatable:
- preemptive: deleverage today (sell collateral, repay debt) just enough to stay above the
  safety target after the shock. net_benefit = penalty avoided - cost (fees + gas + price
  impact + foregone carry). The mark loss avoided on the sold collateral is reported
  separately: it is a de-risking gain, not a liquidation saving.
- during_oracle_lag: if the oracle lags the market, deleverage after the market moves but
  before the oracle updates. Benefit = penalty avoided.
"""

from __future__ import annotations

from backend.risk.liquidity import haircut
from backend.risk.metrics import deleverage_needed
from backend.risk.model import Portfolio, ScenarioOutcome, Snapshot


def _trade_cost(size: float, snapshot: Snapshot, venue_id: str) -> float | None:
    venue = snapshot.venues.get(venue_id)
    if venue is None:
        return None
    return haircut(size, venue.effective_depth_usd) + venue.fee_rate * size + venue.gas_usd


def protection(portfolio: Portfolio, snapshot: Snapshot, outcome: ScenarioOutcome, horizon_days: int, lag_hours: float) -> list[dict]:
    positions = {p.position_id: p for p in portfolio.positions}
    rows = []
    for impact in outcome.impacts:
        penalty = impact.loss_components.get("liquidation_penalty", 0.0)
        if penalty <= 0 or "market" not in impact.internals:
            continue
        position = positions[impact.position_id]
        market = impact.internals["market"]
        oracle_factor = impact.internals["oracle_collateral_after"] / impact.gross_before
        debt = impact.debt_after

        size = deleverage_needed(market, impact.gross_before, debt, oracle_factor)
        trade = _trade_cost(size, snapshot, position.exit_venue_id)
        y = snapshot.yields.get(position.position_id, {})
        carry = size * (y.get("collateral_supply_apy", 0.0) - y.get("debt_borrow_apy", 0.0)) * horizon_days / 365
        market_drop = (impact.gross_before - impact.gross_after) / impact.gross_before
        preemptive = None
        if trade is not None:
            cost = trade + carry
            mark_avoided = size * market_drop
            preemptive = {
                "deleverage_usd": size,
                "cost_usd": cost,
                "penalty_avoided_usd": penalty,
                "mark_loss_avoided_usd": mark_avoided,
                "net_benefit_usd": penalty - cost,
            }

        during_lag = None
        if lag_hours > 0:
            size_lag = deleverage_needed(market, impact.internals["oracle_collateral_after"], debt)
            trade_lag = _trade_cost(size_lag, snapshot, position.exit_venue_id)
            if trade_lag is not None:
                during_lag = {
                    "window_hours": lag_hours,
                    "deleverage_usd": size_lag,
                    "cost_usd": trade_lag,
                    "penalty_avoided_usd": penalty,
                    "net_benefit_usd": penalty - trade_lag,
                }

        rows.append({
            "position_id": impact.position_id,
            "liquidation_penalty_usd": penalty,
            "preemptive": preemptive,
            "during_oracle_lag": during_lag,
        })
    return rows
