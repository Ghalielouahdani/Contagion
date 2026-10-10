"""Lender positions: supplying the loan asset (e.g. USDC) to an isolated lending market (Morpho Blue).

The lender never holds the collateral: borrowers do. A collateral shock reaches the lender only
through borrowers whose collateral stops covering their debt. Market aggregates cannot say how
many borrowers that is, so the market snapshot carries a borrower distribution: buckets of debt
by current oracle LTV (observed when indexed, otherwise labelled assumed).

Per bucket (debt d, oracle LTV l before, collateral C0 = d / l at the oracle price):
- oracle collateral after  C_o = C0 x (1 + pass_through x move) x (1 + rate_cut)
- market collateral after  C_m = C0 x (1 + move) x (1 + rate_cut)
- liquidatable (d / C_o > LLTV): liquidators repay at most C_o / LIF (LIF = 1 + incentive) and
  take all the collateral; the unrepaid rest is realised bad debt, socialised to suppliers pro rata.
- not liquidatable, but C_m < d (the oracle does not see the move): the borrower is underwater at
  market prices and a rational borrower walks away. The protocol has not realised it yet:
  undercollateralized_debt. This is where an exchange-rate oracle that "protects" borrowers moves
  the loss: onto the lenders.
Lender loss = supply share x (bad debt + undercollateralized debt).

Exit: a lender withdraws from the market's idle liquidity (supply - borrow), not through a DEX.
What cannot be withdrawn is locked until borrowers repay: a delay, not a loss.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.risk.model import Position, Snapshot

LENDING_SUPPLY = "lending_supply"


def is_lender(position: Position) -> bool:
    return position.position_type == LENDING_SUPPLY


@dataclass(frozen=True)
class LenderShock:
    share: float  # our supply / total market supply
    bad_debt: float  # market-wide, realised by liquidations
    undercollateralized: float  # market-wide, underwater but not liquidatable by the oracle
    liquidatable_debt: float  # market-wide debt of liquidatable buckets
    total_debt: float


def market_buckets(market: dict) -> list[tuple[float, float]] | None:
    """(debt, oracle LTV) per borrower bucket, or None without a borrower distribution."""
    buckets = market.get("borrower_ltv_buckets")
    if not buckets or market.get("total_borrow_assets") is None:
        return None
    total = float(market["total_borrow_assets"])
    return [(total * float(b["debt_share"]), float(b["ltv"])) for b in buckets]


def supply_share(position: Position, market: dict) -> float | None:
    supply = market.get("total_supply_assets")
    if supply is None or float(supply) <= 0:
        return None
    return min(position.quantity / float(supply), 1.0)


def shock(position: Position, market: dict, move, pass_through: float, rate_cut: float = 0.0) -> LenderShock | None:
    """Lender loss drivers when the collateral market price moves by `move` (plus an exchange-rate cut)."""
    buckets, share = market_buckets(market), supply_share(position, market)
    if buckets is None or share is None:
        return None
    lltv = float(market["lltv"])
    lif = 1 + float(market.get("liquidation_incentive", 0))
    bad = under = liquidatable = 0.0
    for debt, ltv in buckets:
        if debt <= 0 or ltv <= 0:
            continue
        c0 = debt / ltv
        c_oracle = c0 * (1 + pass_through * move) * (1 + rate_cut)
        c_market = c0 * (1 + move) * (1 + rate_cut)
        if c_oracle <= 0 or debt / c_oracle > lltv:
            liquidatable += debt
            bad += max(debt - max(c_oracle, 0.0) / lif, 0.0)
        else:
            under += max(debt - max(c_market, 0.0), 0.0)
    return LenderShock(share, bad, under, liquidatable, sum(d for d, _ in buckets))


def withdrawable(position: Position, market: dict, liquidity_reduction: float = 0.0) -> float | None:
    """Loan asset the position can withdraw now: idle market liquidity, after other lenders took their part."""
    supply, borrow = market.get("total_supply_assets"), market.get("total_borrow_assets")
    if supply is None or borrow is None:
        return None
    idle = max(float(supply) - float(borrow), 0.0) * (1 - liquidity_reduction)
    return min(position.quantity, idle)


def exit_note(position: Position, snapshot: Snapshot, liquidity_reduction: float) -> tuple[str, bool]:
    """(warning, data missing) for a lender's exit in a liquidity scenario. Locked supply is a delay, not a loss."""
    market = snapshot.market(position.position_id)
    available = None if market is None else withdrawable(position, market, liquidity_reduction)
    if available is None:
        return "No market supply/borrow data: withdrawable amount not computed.", True
    locked = position.quantity - available
    if locked <= 0:
        return f"Lender exit: the full {position.quantity:,.0f} {position.asset_symbol} can be withdrawn from idle market liquidity.", False
    return (f"Lender exit: only {available:,.0f} of {position.quantity:,.0f} {position.asset_symbol} can be withdrawn now; "
            f"{locked:,.0f} stays locked until borrowers repay or new supply arrives (a delay, not a loss)."), False
