"""Liquidation metrics per lending protocol (blueprint section 7.1).

A metric is registered per market_kind, mirroring contracts/schemas/v1/markets/.
Adding a lending protocol = one function + one @register line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def health_factor(collateral_value, liquidation_threshold, debt_value):
    return collateral_value * liquidation_threshold / debt_value


def ltv(debt_value, collateral_value):
    return debt_value / collateral_value


def hf_distance_to_liquidation(hf):
    """Fraction the collateral oracle price can fall before HF < 1 (single collateral, stable debt)."""
    return 1 - 1 / hf


def ltv_distance_to_liquidation(ltv_value, lltv):
    """Fraction the collateral oracle price can fall before LTV > LLTV."""
    return 1 - ltv_value / lltv


def deleverage_to_hf(collateral, debt, liquidation_threshold, target_hf):
    """USD of collateral to sell and repay as debt so that HF reaches target_hf (0 if already safe)."""
    needed = (target_hf * debt - collateral * liquidation_threshold) / (target_hf - liquidation_threshold)
    return max(needed, 0.0)


def deleverage_to_ltv(collateral, debt, target_ltv):
    """USD of collateral to sell and repay as debt so that LTV falls to target_ltv (0 if already safe)."""
    needed = (debt - target_ltv * collateral) / (1 - target_ltv)
    return max(needed, 0.0)


@dataclass(frozen=True)
class MetricReading:
    type: str
    before: float
    after: float
    threshold: float
    liquidatable: bool
    distance_before: float
    distance_after: float
    liquidation_incentive: float
    close_factor: float  # share of debt liquidators may repay at the post-shock metric


@dataclass(frozen=True)
class MetricRule:
    metric_type: str
    compute: Callable[[dict, float, float], tuple[float, float]]  # (market, collateral, debt) -> (value, distance)
    threshold: Callable[[dict], float]
    breached: Callable[[float, float], bool]  # (value, threshold) -> liquidatable
    incentive_field: str
    close_factor: Callable[[float], float]  # metric value -> max share of debt repaid in one liquidation
    # (market, collateral, debt, oracle_factor) -> USD to sell and repay now so the position is still safe
    # after the oracle moves by oracle_factor (1.0 = deleverage at current prices).
    deleverage: Callable[[dict, float, float, float], float]


RULES: dict[str, MetricRule] = {}


def register(market_kind: str, rule: MetricRule) -> None:
    RULES[market_kind] = rule


def _aave(market: dict, collateral: float, debt: float) -> tuple[float, float]:
    hf = health_factor(collateral, float(market["liquidation_threshold"]), debt)
    return hf, hf_distance_to_liquidation(hf)


def _morpho(market: dict, collateral: float, debt: float) -> tuple[float, float]:
    value = ltv(debt, collateral)
    return value, ltv_distance_to_liquidation(value, float(market["lltv"]))


# Safety targets used when sizing a pre-emptive deleverage.
SAFE_HF = 1.05
SAFE_LTV_SHARE_OF_LLTV = 0.95

register("aave_v3_reserve", MetricRule(
    "health_factor", _aave, lambda m: 1.0, lambda v, t: v < t, "liquidation_bonus",
    # Aave v3: 50% of the debt per liquidation while HF >= 0.95, 100% below.
    close_factor=lambda hf: 0.5 if hf >= 0.95 else 1.0,
    deleverage=lambda m, c, d, f: deleverage_to_hf(c, d, float(m["liquidation_threshold"]) * f, SAFE_HF),
))
register("morpho_blue_market", MetricRule(
    "ltv", _morpho, lambda m: float(m["lltv"]), lambda v, t: v > t, "liquidation_incentive",
    # Morpho Blue has no close factor: the whole position can be liquidated at once.
    close_factor=lambda ltv_value: 1.0,
    deleverage=lambda m, c, d, f: deleverage_to_ltv(c, d, SAFE_LTV_SHARE_OF_LLTV * float(m["lltv"]) * f),
))


def read_metric(market: dict, oracle_collateral_before: float, oracle_collateral_after: float, debt_before: float, debt_after: float) -> MetricReading:
    rule = RULES.get(market["market_kind"])
    if rule is None:
        raise KeyError(f"no liquidation metric registered for market_kind {market['market_kind']!r}")
    before, dist_before = rule.compute(market, oracle_collateral_before, debt_before)
    after, dist_after = rule.compute(market, oracle_collateral_after, debt_after)
    threshold = rule.threshold(market)
    return MetricReading(
        type=rule.metric_type,
        before=before,
        after=after,
        threshold=threshold,
        liquidatable=bool(rule.breached(after, threshold)),
        distance_before=dist_before,
        distance_after=dist_after,
        liquidation_incentive=float(market.get(rule.incentive_field, 0)),
        close_factor=rule.close_factor(after),
    )


def deleverage_needed(market: dict, collateral: float, debt: float, oracle_factor: float = 1.0) -> float:
    """USD of collateral to sell and repay today so the position stays above the safety target
    after its collateral oracle moves by oracle_factor (e.g. 0.70 for a 30% oracle drop)."""
    return RULES[market["market_kind"]].deleverage(market, collateral, debt, oracle_factor)
