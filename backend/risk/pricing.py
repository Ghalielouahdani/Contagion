"""Asset pricing: market prices, Pendle PT proxy and oracle prices (blueprint section 7.1).

Everything is plain arithmetic, so the functions accept floats or NumPy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.risk.model import Position, Snapshot

SUSDE_RATE_KEY = "sUSDe_USDe"
STABLES = ("USDC", "USDT", "DAI", "PYUSD", "RLUSD")  # debt assets priced at their own observed price (not shocked by USDe scenarios)


@dataclass(frozen=True)
class MarketState:
    """Prices of the risk factors at one point (before or after a shock)."""

    usde_usd: float  # USDe market price
    susde_usd: float  # sUSDe market price
    stable_usd: float = 1.0  # default price of a debt stablecoin without its own observed price
    pt_apy_shift: float = 0.0  # additive shock to every PT implied APY
    susde_rate_factor: float = 1.0  # cumulative sUSDe exchange-rate cut (PT-sUSDe redeems into it)
    fundamental_factor: float = 1.0  # uniform value shock (liquidity scenario)
    stables: tuple[tuple[str, float], ...] = ()  # observed price per debt stablecoin

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> MarketState:
        usde = snapshot.prices_usd["USDe"]
        rate = snapshot.exchange_rates[SUSDE_RATE_KEY]
        default = snapshot.prices_usd.get("USDC", 1.0)
        stables = tuple((s, snapshot.prices_usd.get(s, default)) for s in STABLES)
        return cls(usde_usd=usde, susde_usd=rate * usde, stable_usd=default, stables=stables)

    def shocked(
        self,
        usde_shock: float = 0.0,
        susde_beta: float = 1.0,
        impairment: float = 0.0,
        pt_apy_shift: float = 0.0,
        fundamental_shock: float = 0.0,
        susde_rate_cut: float = 0.0,
    ) -> MarketState:
        """Three distinct mechanisms, each applied once:

        - usde_shock: USDe market price move; sUSDe moves by beta x usde_shock.
        - impairment: loss of USDe backing; the market reprices both USDe and sUSDe.
        - susde_rate_cut: loss socialised to stakers; only the sUSDe exchange rate falls.
        """
        return replace(
            self,
            usde_usd=self.usde_usd * (1 + usde_shock) * (1 + impairment),
            susde_usd=self.susde_usd * (1 + susde_beta * usde_shock) * (1 + impairment) * (1 + susde_rate_cut),
            pt_apy_shift=self.pt_apy_shift + pt_apy_shift,
            susde_rate_factor=self.susde_rate_factor * (1 + susde_rate_cut),
            fundamental_factor=self.fundamental_factor * (1 + fundamental_shock),
        )


def pt_price(underlying_usd, implied_apy, days_to_maturity):
    """PT proxy: redemption value discounted at the implied APY; equals the underlying at maturity."""
    if days_to_maturity <= 0:
        return underlying_usd
    return underlying_usd / (1 + implied_apy) ** (days_to_maturity / 365)


def asset_price(symbol: str, state: MarketState, market: dict | None = None):
    if symbol == "USDe":
        price = state.usde_usd
    elif symbol == "sUSDe":
        price = state.susde_usd
    elif symbol in STABLES:
        return dict(state.stables).get(symbol, state.stable_usd)
    elif symbol.startswith("PT-"):
        if market is None:
            raise ValueError(f"{symbol} needs its Pendle market parameters")
        apy = float(market["pt_implied_apy"]) + state.pt_apy_shift
        # PT-sUSDe redeems into sUSDe worth 1 USDe at maturity: a rate cut lowers that claim.
        price = pt_price(state.usde_usd * state.susde_rate_factor, apy, float(market["days_to_maturity"]))
    else:
        raise KeyError(f"no pricing rule for asset {symbol!r}")
    return price * state.fundamental_factor


def position_values(position: Position, state: MarketState, snapshot: Snapshot) -> tuple[float, float]:
    """(gross mark value, debt value) of a position in a given market state."""
    market = snapshot.market(position.position_id)
    if position.is_borrow:
        gross = position.collateral_quantity * asset_price(position.collateral_asset, state, market)
        debt = position.debt_quantity * asset_price(position.debt_asset, state, market)
        return gross, debt
    return position.quantity * asset_price(position.asset_symbol, state, market), 0.0


def oracle_price(base_price, market_move, pass_through, rate_cut=0.0):
    """Price the protocol's oracle reports.

    market_move: market price move excluding any sUSDe rate cut (depeg + backing impairment).
    pass_through = 1: market price feed; 0: exchange-rate oracle with USDe hardcoded at 1 USD,
    which ignores both the depeg and a USDe backing loss.
    rate_cut: sUSDe exchange-rate cut; every sUSDe oracle reads the rate, so all see it.
    """
    return base_price * (1 + pass_through * market_move) * (1 + rate_cut)
