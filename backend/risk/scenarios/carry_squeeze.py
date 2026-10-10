"""Scenario D: carry squeeze. No price moves; the rates turn against the portfolio over time.

Ethena's main risk in practice: perp funding turns negative, sUSDe yield falls to zero (or
below once the reserve fund is spent), and stablecoin borrow rates spike when lending pools
hit their utilization kink. Over horizon_days, with simple interest:
- sUSDe exchange rate grows by susde_apy (a negative APY lowers it, and PT-sUSDe's claim with it);
- lending collateral accrues its supply APY, debt accrues the borrow APY: HF / LTV erode;
- PT pulls to par as maturity gets closer (plus an optional implied-yield shock).

Loss is measured against today's net equity, so a carry that stays positive shows as a negative
loss (a gain). The comparison block reports the carry at the snapshot's current rates; the
excess is what the squeeze costs on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.risk.metrics import read_metric
from backend.risk.model import Portfolio, Position, PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.pricing import MarketState, position_values
from backend.risk.scenarios import scenario

MAX_DAYS = 3650  # search window for days to liquidation


@dataclass(frozen=True)
class Rates:
    susde_apy: float
    supply_override: float | None  # lending supply APY on collateral; None = snapshot per position
    borrow_override: float | None  # borrow APY on debt; None = snapshot per position
    pt_apy_shock: float = 0.0


@scenario("carry_squeeze")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    stressed = Rates(
        susde_apy=request.param("susde_apy", 0.0),
        supply_override=request.param("collateral_supply_apy_override"),
        borrow_override=request.param("borrow_apy_override"),
        pt_apy_shock=request.param("pt_implied_apy_shock", 0.0),
    )
    outcome = simulate(portfolio, snapshot, request.horizon_days, stressed)

    for position, impact in zip(portfolio.positions, outcome.impacts):
        if position.is_borrow and impact.risk_metric is not None:
            days = days_to_liquidation(position, snapshot, stressed)
            if days is not None:
                impact.warnings.append(f"At these rates the position becomes liquidatable after about {days} days.")

    current = current_susde_apy(portfolio, snapshot)
    if current is None:
        outcome.warnings.append("No current sUSDe APY in the snapshot yields: carry at current rates not reported.")
    else:
        baseline = simulate(portfolio, snapshot, request.horizon_days, Rates(current, None, None))
        outcome.comparison = {
            "runs": [{"run_id": "carry_at_current_rates",
                      "description": f"Same horizon at the snapshot's rates (sUSDe APY {current:.2%}).",
                      "total_loss": sum(sum(i.loss_components.values()) for i in baseline.impacts)}],
            "excess_meaning": "Cost of the squeeze: carry lost versus keeping today's rates over the horizon.",
        }
    outcome.warnings.append(f"Rates applied as simple interest over {request.horizon_days} days; no price shock.")
    return outcome


def simulate(portfolio: Portfolio, snapshot: Snapshot, days: float, rates: Rates) -> ScenarioOutcome:
    t = days / 365
    before = MarketState.from_snapshot(snapshot)
    growth = max(1 + rates.susde_apy * t, 0.0)  # simple interest cannot take the rate below zero
    carry_state = replace(before, susde_usd=before.susde_usd * growth,
                          susde_rate_factor=before.susde_rate_factor * min(growth, 1.0))
    after_state = replace(carry_state, pt_apy_shift=carry_state.pt_apy_shift + rates.pt_apy_shock)
    aged = _aged(snapshot, days)

    outcome = ScenarioOutcome(impacts=[])
    for position in portfolio.positions:
        gross0, debt0 = position_values(position, before, snapshot)
        accrued = _accrue(position, snapshot, rates, t)
        gross_c, debt_c = position_values(accrued, carry_state, aged)
        gross1, debt1 = position_values(accrued, after_state, aged)
        impact = PositionImpact(
            position_id=position.position_id,
            gross_before=gross0,
            gross_after=gross1,
            debt_after=debt1,
            net_before=gross0 - debt0,
            loss_components={
                "market_repricing": (gross_c - debt_c) - (gross1 - debt1),  # PT implied-yield shock
                "backing_impairment": 0.0,
                "liquidation_penalty": 0.0,
                "execution_haircut": 0.0,
                "negative_carry": (gross0 - debt0) - (gross_c - debt_c),
            },
        )
        if position.is_borrow:
            _liquidation(impact, position, snapshot, gross0, debt0)
        outcome.impacts.append(impact)
    return outcome


def _liquidation(impact: PositionImpact, position: Position, snapshot: Snapshot, gross0: float, debt0: float) -> None:
    market = snapshot.market(position.position_id)
    if market is None:
        impact.insufficient_data = True
        impact.warnings.append("No market parameters: liquidation risk not computed.")
        return
    if impact.gross_after <= 0:
        # Collateral worth nothing: HF / LTV are undefined and the position is gone, not "liquidatable".
        impact.warnings.append("Collateral value reaches 0 over the horizon: the position is wiped out.")
        return
    # No depeg: every oracle reads the market value (an exchange-rate oracle reads the accrued sUSDe rate).
    metric = read_metric(market, gross0, impact.gross_after, debt0, impact.debt_after)
    impact.risk_metric = metric.as_contract()
    impact.internals = {"market": market, "oracle_collateral_after": impact.gross_after, "metric": metric}
    if metric.liquidatable:
        impact.loss_components["liquidation_penalty"] = metric.close_factor * impact.debt_after * metric.liquidation_incentive
        impact.warnings.append(
            f"Liquidatable from accrued debt alone: liquidators may repay {metric.close_factor:.0%} of the debt.")


def days_to_liquidation(position: Position, snapshot: Snapshot, rates: Rates) -> int | None:
    """First whole day the position is liquidatable at these rates (None if not within MAX_DAYS)."""
    market = snapshot.market(position.position_id)
    if market is None:
        return None

    def liquidatable(days: int) -> bool:
        impact = simulate(Portfolio("probe", (position,)), snapshot, days, rates).impacts[0]
        return impact.gross_after <= 0 or bool(impact.risk_metric and impact.risk_metric["liquidatable"])

    if liquidatable(0) or not liquidatable(MAX_DAYS):
        return None
    lo, hi = 0, MAX_DAYS  # not liquidatable at lo, liquidatable at hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if liquidatable(mid) else (mid, hi)
    return hi


def current_susde_apy(portfolio: Portfolio, snapshot: Snapshot) -> float | None:
    for position in portfolio.positions:
        if position.asset_symbol == "sUSDe" and "token_apy" in snapshot.yields.get(position.position_id, {}):
            return snapshot.yields[position.position_id]["token_apy"]
    return None


def _accrue(position: Position, snapshot: Snapshot, rates: Rates, t: float) -> Position:
    if not position.is_borrow:
        return position
    y = snapshot.yields.get(position.position_id, {})
    supply = y.get("collateral_supply_apy", 0.0) if rates.supply_override is None else rates.supply_override
    borrow = y.get("debt_borrow_apy", 0.0) if rates.borrow_override is None else rates.borrow_override
    return replace(position, collateral_quantity=position.collateral_quantity * (1 + supply * t),
                   debt_quantity=position.debt_quantity * (1 + borrow * t))


def _aged(snapshot: Snapshot, days: float) -> Snapshot:
    """Snapshot `days` later: maturities are closer (PT pulls to par)."""
    markets = {
        pid: {**m, "days_to_maturity": str(max(float(m["days_to_maturity"]) - days, 0.0))} if "days_to_maturity" in m else m
        for pid, m in snapshot.markets.items()
    }
    return replace(snapshot, markets=markets)
