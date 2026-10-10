"""Typed views of the schema v1 contracts used by the risk engine.

Contract numbers are decimal strings; the engine computes in float64 (so the same
formulas also run on NumPy arrays for sensitivity grids) and only rounds at output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def num(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class Position:
    position_id: str
    protocol: str
    position_type: str
    exit_venue_id: str
    gross_value_usd: float
    debt_value_usd: float
    net_equity_usd: float
    data_origin: str
    asset_symbol: str | None = None
    quantity: float | None = None
    collateral_asset: str | None = None
    collateral_quantity: float | None = None
    debt_asset: str | None = None
    debt_quantity: float | None = None

    @property
    def is_borrow(self) -> bool:
        return self.position_type == "collateralized_borrow"

    @classmethod
    def from_contract(cls, raw: dict) -> Position:
        return cls(
            position_id=raw["position_id"],
            protocol=raw["protocol"],
            position_type=raw["position_type"],
            exit_venue_id=raw["exit_venue_id"],
            gross_value_usd=float(raw["gross_value_usd"]),
            debt_value_usd=float(raw["debt_value_usd"]),
            net_equity_usd=float(raw["net_equity_usd"]),
            data_origin=raw["data_origin"],
            asset_symbol=raw.get("asset_symbol"),
            quantity=num(raw.get("quantity")),
            collateral_asset=raw.get("collateral_asset"),
            collateral_quantity=num(raw.get("collateral_quantity")),
            debt_asset=raw.get("debt_asset"),
            debt_quantity=num(raw.get("debt_quantity")),
        )


@dataclass(frozen=True)
class Venue:
    venue_id: str
    asset: str
    effective_depth_usd: float
    quote_method: str
    fee_rate: float = 0.0
    gas_usd: float = 0.0
    # Executable quotes: (size_usd, all-in loss fraction), sorted by size. Empty = proxy depth only.
    curve: tuple[tuple[float, float], ...] = ()
    depth_scale: float = 1.0  # sensitivity multiplier on the venue's depth (1 = as observed)

    @staticmethod
    def curve_from_quotes(quotes: list[dict]) -> tuple[tuple[float, float], ...]:
        points = {float(q["size_usd"]): float(q["loss_pct"]) / 100 for q in quotes if float(q["size_usd"]) > 0}
        return tuple(sorted(points.items()))


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    prices_usd: dict[str, float]
    exchange_rates: dict[str, float]
    markets: dict[str, dict]  # position_id -> raw market params (kept raw: shape depends on market_kind)
    venues: dict[str, Venue]
    verified: bool
    yields: dict[str, dict[str, float]] = field(default_factory=dict)  # position_id -> {token_apy, collateral_supply_apy, debt_borrow_apy}

    def market(self, position_id: str) -> dict | None:
        return self.markets.get(position_id)

    @classmethod
    def from_contract(cls, raw: dict) -> Snapshot:
        markets = raw.get("markets", {})
        return cls(
            snapshot_id=raw["snapshot_id"],
            prices_usd={k: float(v["value"]) for k, v in raw.get("prices_usd", {}).items()},
            exchange_rates={k: float(v["value"]) for k, v in raw.get("exchange_rates", {}).items()},
            markets=markets,
            venues={
                vid: Venue(vid, v["asset"], float(v["effective_depth_usd"]), v["quote_method"],
                           float(v.get("fee_rate", 0)), float(v.get("gas_usd", 0)),
                           Venue.curve_from_quotes(v.get("quotes", [])))
                for vid, v in raw.get("exit_venues", {}).items()
            },
            verified=bool(markets) and all(m.get("verified", False) for m in markets.values()),
            yields={
                pid: {k: float(v) for k, v in y.items() if k.endswith("_apy")}
                for pid, y in raw.get("yields", {}).items()
            },
        )


@dataclass(frozen=True)
class Portfolio:
    portfolio_id: str
    positions: tuple[Position, ...]

    @classmethod
    def from_contract(cls, raw: dict) -> Portfolio:
        return cls(raw["portfolio_id"], tuple(Position.from_contract(p) for p in raw["positions"]))


@dataclass(frozen=True)
class ScenarioRequest:
    request_id: str
    portfolio_id: str
    snapshot_id: str
    graph_id: str
    scenario_id: str
    horizon_days: int
    parameters: dict[str, Any]
    probability: float | None = None

    def param(self, name: str, default: float | None = None) -> float | None:
        value = self.parameters.get(name, default)
        return default if value is None else float(value)

    @classmethod
    def from_contract(cls, raw: dict) -> ScenarioRequest:
        scenario = raw["scenario"]
        return cls(
            request_id=raw["request_id"],
            portfolio_id=raw["portfolio_id"],
            snapshot_id=raw["snapshot_id"],
            graph_id=raw["graph_id"],
            scenario_id=scenario["scenario_id"],
            horizon_days=scenario["horizon_days"],
            parameters=scenario["parameters"],
            probability=num(raw.get("assumptions", {}).get("probability")),
        )


@dataclass
class PositionImpact:
    """Unrounded per-position result; report.py turns it into the contract shape."""

    position_id: str
    gross_before: float
    gross_after: float
    debt_after: float
    net_before: float
    loss_components: dict[str, float]
    executable_after: float | None = None
    risk_metric: dict | None = None
    insufficient_data: bool = False
    warnings: list[str] = field(default_factory=list)
    internals: dict = field(default_factory=dict)  # unrounded facts for analytics; never published
    contagion: dict | None = None  # paths, evidence confidence, graph gaps (set by contagion.annotate)


@dataclass
class ScenarioOutcome:
    impacts: list[PositionImpact]
    shared_liquidity_penalty: float = 0.0
    warnings: list[str] = field(default_factory=list)
    contagion: dict | None = None  # graph id, hubs, warnings (set by contagion.annotate)
    # Reference runs on the same portfolio and what this scenario adds on top of them
    # ({"runs": [{"run_id", "description", "total_loss"}], "excess_meaning"}); excess = total - sum(runs).
    comparison: dict | None = None
    cascade: dict | None = None  # rounds, moves, amplification (liquidation_cascade only; see cascade.py)
