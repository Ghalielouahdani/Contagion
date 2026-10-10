"""Liquidation cascade: forced selling feeds back into prices until no new liquidation is triggered.

    initial shock -> borrowers liquidatable (through each market's oracle) -> liquidators seize and
    sell collateral on the collateral's exit venue -> price impact -> more borrowers liquidatable -> ...

Inspired by agent-based risk simulations (Gauntlet) and liquidation-cascade monitors, reduced to
deterministic rules that run in milliseconds:
- borrowers: each market's borrower LTV buckets (lending.py), plus our own borrow positions in
  markets that have no bucket data (otherwise they are already inside the buckets);
- oracle: a market sees the collateral's market move times its oracle pass-through. An
  exchange-rate oracle (pass-through 0) never sees the cascade: it is a circuit breaker;
- liquidators, two behaviours (`impact_aware`):
  * price takers (default, the classic cascade and the worst case): they liquidate whatever is
    profitable at the current price (seized > repaid) and the market absorbs their selling; the
    price impact of a round's selling hits the next round;
  * impact aware: they act only while it pays. A bucket is many borrowers, so it is liquidated in part:
  liquidators keep going while the next dollar of collateral they sell (behind the forced selling
  already queued on the venue) still earns more than the debt it repays, i.e. while the venue's
  marginal discount stays below 1 - repaid / seized (1 - 1 / LIF when the oracle reads the market).
  The rest stays unliquidated ("stuck" when liquidatable but unprofitable): it stops the cascade
  but leaves underwater debt with the lenders. With liquidators selling at once, the self-inflicted
  price drop is therefore bounded by the liquidation incentive;
- price impact: the price after forced selling Q still weighing on the market is the venue's
  marginal price, move = (1 + initial move) x (1 - marginal discount at Q) - 1, from the venue's
  executable quote curve or proxy depth (liquidity.exit_cost) at the scenario's crisis depth;
- arbitrage: between rounds a share `absorption` of the selling stops weighing on the price
  (arbitrageurs buy the discount; for USDe, minting/redeeming at par while the backing holds).
  0 = nothing is absorbed (cumulative impact, worst case), 1 = each round's impact fully recovers
  before the next. This is the cascade's least known parameter: calibrate it on a real episode;
- bad debt is measured at the price of the round in which a bucket is liquidated.
Each bucket is liquidated at most once, so the loop ends after at most (number of buckets + 1)
rounds; MAX_ROUNDS is a safety net. USDe and sUSDe move on their own venues; arbitrage between
them is not modeled (initial sUSDe move = beta x USDe move). A model, labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.risk.lending import is_lender, market_buckets
from backend.risk.liquidity import exit_cost
from backend.risk.metrics import RULES
from backend.risk.model import Portfolio, Snapshot, Venue

MAX_ROUNDS = 50
MAX_DISCOUNT = 0.99
CASCADE_ASSETS = ("USDe", "sUSDe")


@dataclass
class Bucket:
    market: str  # snapshot market key (position id)
    asset: str  # collateral symbol
    debt: float
    collateral0: float  # collateral value before the shock (oracle = market)
    lltv: float
    lif: float  # liquidation incentive factor, 1 + incentive
    pass_through: float
    origin: str  # "market" (borrower bucket) or "position" (our own borrow)
    liquidated: float = 0.0  # debt liquidated so far
    bad_debt: float = 0.0  # realised on the liquidated part, at liquidation-time prices
    stuck: bool = False  # liquidatable but no longer profitable to liquidate

    @property
    def remaining(self) -> float:
        return self.debt - self.liquidated


@dataclass
class CascadeResult:
    moves: dict[str, float]  # final market move per asset (after the last round's arbitrage)
    initial_moves: dict[str, float]
    troughs: dict[str, float] = field(default_factory=dict)  # lowest move reached per asset
    rounds: list[dict] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)
    converged: bool = True
    warnings: list[str] = field(default_factory=list)

    def market_losses(self, market: str) -> tuple[float, float]:
        """(realised bad debt, underwater debt not liquidated) for one market, at final prices."""
        bad = under = 0.0
        for b in self.buckets:
            if b.market != market or b.origin != "market":
                continue
            bad += b.bad_debt
            left = b.remaining / b.debt
            under += max(b.remaining - b.collateral0 * left * (1 + self.moves[b.asset]), 0.0)
        return bad, under


def venue_for(snapshot: Snapshot, asset: str) -> Venue | None:
    return next((v for v in snapshot.venues.values() if v.asset == asset), None)


def marginal_discount(venue: Venue, sold: float, depth_factor: float) -> float:
    """Price discount of the next dollar sold after `sold` USD of forced selling."""
    step = max(sold * 1e-4, 1.0)
    slope = (exit_cost(venue, sold + step, depth_factor) - exit_cost(venue, sold, depth_factor)) / step
    return min(max(slope, 0.0), MAX_DISCOUNT)


def collect_buckets(portfolio: Portfolio, snapshot: Snapshot, pass_through_override: float | None) -> list[Bucket]:
    buckets: list[Bucket] = []
    covered: set[tuple[str, str]] = set()  # (collateral, loan) pairs with borrower data
    for key, market in snapshot.markets.items():
        asset, rows = market.get("collateral_asset"), market_buckets(market)
        if asset not in CASCADE_ASSETS or rows is None:
            continue
        covered.add((asset, market.get("loan_asset", "USDC")))
        for debt, ltv in rows:
            if debt > 0 and ltv > 0:
                buckets.append(_bucket(key, asset, debt, debt / ltv, market, pass_through_override, "market"))
    for position in portfolio.positions:
        market = snapshot.market(position.position_id)
        if (not position.is_borrow or market is None or position.collateral_asset not in CASCADE_ASSETS
                or (position.collateral_asset, position.debt_asset) in covered):
            continue
        rule = RULES.get(market.get("market_kind"))
        if rule is None:
            continue
        buckets.append(_bucket(position.position_id, position.collateral_asset, position.debt_value_usd,
                               position.gross_value_usd, market, pass_through_override, "position"))
    return buckets


def _bucket(key: str, asset: str, debt: float, collateral0: float, market: dict, override: float | None,
            origin: str) -> Bucket:
    kind = market.get("market_kind")
    if kind == "aave_v3_reserve":
        # HF < 1  <=>  debt / collateral > LT: the same breach test as an LLTV.
        lltv, incentive = float(market["liquidation_threshold"]), float(market.get("liquidation_bonus", 0))
    else:
        lltv, incentive = float(market["lltv"]), float(market.get("liquidation_incentive", 0))
    pass_through = override if override is not None else float(market.get("oracle_pass_through", 1.0))
    return Bucket(key, asset, debt, collateral0, lltv, 1 + incentive, pass_through, origin)


def run(portfolio: Portfolio, snapshot: Snapshot, initial_moves: dict[str, float], depth_factor: float,
        pass_through_override: float | None = None, impact_aware: bool = False,
        absorption: float = 0.0) -> CascadeResult:
    buckets = collect_buckets(portfolio, snapshot, pass_through_override)
    venues = {asset: venue_for(snapshot, asset) for asset in CASCADE_ASSETS}
    result = CascadeResult(moves=dict(initial_moves), initial_moves=dict(initial_moves), buckets=buckets,
                           troughs=dict(initial_moves))
    for asset in {b.asset for b in buckets}:
        if venues[asset] is None:
            result.warnings.append(f"No exit venue for {asset} in the snapshot: liquidators' selling has no price "
                                   "impact, the cascade cannot propagate through it.")
    sold = {asset: 0.0 for asset in CASCADE_ASSETS}  # forced selling still weighing on each price

    for round_no in range(1, MAX_ROUNDS + 1):
        liquidated_debt = 0.0
        sold_this_round = {asset: 0.0 for asset in CASCADE_ASSETS}
        for b in buckets:
            if b.remaining <= 0:
                continue
            move = result.moves[b.asset]
            per_debt_collateral = b.collateral0 / b.debt  # oracle = market before the shock
            oracle_per_debt = per_debt_collateral * (1 + b.pass_through * move)
            if oracle_per_debt > 0 and 1 / oracle_per_debt <= b.lltv:
                continue  # not liquidatable at this oracle price
            # Per dollar of debt liquidated: collateral seized (oracle, then market value) and debt repaid.
            seized_oracle = min(b.lif, max(oracle_per_debt, 0.0))
            repaid = seized_oracle / b.lif
            seized = seized_oracle * (1 + move) / (1 + b.pass_through * move) if oracle_per_debt > 0 else 0.0
            if not impact_aware:
                amount = b.remaining if seized > repaid else 0.0
            else:
                amount = _profitable_amount(venues[b.asset], sold[b.asset] + sold_this_round[b.asset], b.remaining,
                                            seized, repaid, depth_factor)
            b.stuck = amount < b.remaining
            if amount <= 0:
                continue
            b.liquidated += amount
            b.bad_debt += amount * max(1 - repaid, 0.0)
            liquidated_debt += amount
            sold_this_round[b.asset] += amount * seized

        for asset, amount in sold_this_round.items():
            sold[asset] = sold[asset] * (1 - absorption) + amount
            if venues[asset] is not None and sold[asset] > 0:
                discount = marginal_discount(venues[asset], sold[asset], depth_factor)
                result.moves[asset] = (1 + initial_moves[asset]) * (1 - discount) - 1
                result.troughs[asset] = min(result.troughs[asset], result.moves[asset])
        result.rounds.append({
            "round": round_no,
            "liquidated_debt_usd": liquidated_debt,
            "collateral_sold_usd": sum(sold_this_round.values()),
            "moves": dict(result.moves),
        })
        if liquidated_debt <= 1.0:  # nothing (or dust) liquidated: fixed point reached
            break
    else:
        result.converged = False
        result.warnings.append(f"Cascade still liquidating after {MAX_ROUNDS} rounds: stopped, result incomplete.")
    stuck = sum(b.remaining for b in buckets if b.stuck)
    if stuck > 0:
        result.warnings.append(
            f"{stuck:,.0f} USD of borrower debt is liquidatable but no longer profitable to liquidate (selling the "
            "seized collateral would cost more than the incentive): it stops the cascade and stays with the lenders "
            "as underwater or at-risk debt.")
    return result


def _profitable_amount(venue: Venue | None, queued: float, remaining: float, seized: float, repaid: float,
                       depth_factor: float) -> float:
    """Debt liquidators liquidate before the marginal discount on the venue eats their margin."""
    if seized <= 0 or seized <= repaid:
        return 0.0
    if venue is None:
        return remaining  # no venue data: selling assumed costless (flagged by the caller)
    threshold = 1 - repaid / seized
    if marginal_discount(venue, queued, depth_factor) >= threshold:
        return 0.0
    if marginal_discount(venue, queued + remaining * seized, depth_factor) < threshold:
        return remaining
    lo, hi = 0.0, remaining
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if marginal_discount(venue, queued + mid * seized, depth_factor) < threshold else (lo, mid)
    return lo


def lender_losses(result: CascadeResult, portfolio: Portfolio, snapshot: Snapshot) -> dict[str, tuple[float, float]]:
    """position_id -> (bad debt, undercollateralized debt) of each lender position, at its supply share."""
    out = {}
    for position in portfolio.positions:
        market = snapshot.market(position.position_id)
        if not is_lender(position) or market is None or market.get("total_supply_assets") in (None, "0"):
            continue
        share = min(position.quantity / float(market["total_supply_assets"]), 1.0)
        bad, under = result.market_losses(position.position_id)
        out[position.position_id] = (share * bad, share * under)
    return out

