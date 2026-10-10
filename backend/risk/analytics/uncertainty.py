"""Model uncertainty: one scenario, many plausible model assumptions -> a range, not one number.

The scenario stays fixed (its severity parameters are not touched: the loss curves cover them).
What varies are the model assumptions the engine cannot observe:
- sUSDe beta to USDe; the oracle pass-through of markets whose oracle is not verified;
- liquidation thresholds and PT implied APY of unverified markets;
- exit depth of each venue (wider range when the depth is an assumption than when it is quoted);
- the cascade's arbitrage absorption.
Verified inputs never vary. Each draw is a full engine run; draws are uniform within each
assumption's range (log-uniform for depth multipliers), with a fixed seed so the result is
reproducible. The output is the conditional loss distribution *given the scenario*: it says how
much the answer depends on what we do not know, never how likely the scenario is.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from backend.risk.analytics.runner import total_loss
from backend.risk.analytics.sensitivity import Assumption, _apply
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot
from backend.risk import scenarios

DRAWS = 256
SEED = 20261010
PERCENTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
DEPEG_LIKE = ("usde_depeg", "combined_crisis", "governance_change", "liquidation_cascade", "node_shock")


@dataclass(frozen=True)
class Range:
    assumption: Assumption
    log: bool = False  # draw log-uniformly (multipliers)


def model_assumptions(snapshot: Snapshot, request: ScenarioRequest) -> list[Range]:
    sid = request.scenario_id
    rows: list[Range] = []
    if sid in DEPEG_LIKE and sid != "node_shock":
        rows.append(Range(Assumption("sUSDe beta to USDe", "param", "susde_market_beta", 0.5, 1.5)))
    if request.parameters.get("oracle_pass_through_override") is None:
        for key, market in snapshot.markets.items():
            if "oracle_pass_through" in market and not market.get("verified"):
                rows.append(Range(Assumption(f"{key} oracle pass-through", "market", f"{key}.oracle_pass_through", 0.0, 1.0)))
    for key, market in snapshot.markets.items():
        if market.get("verified"):
            continue
        kind = market.get("market_kind")
        if kind == "aave_v3_reserve":
            lt = float(market["liquidation_threshold"])
            rows.append(Range(Assumption(f"{key} liquidation threshold", "market", f"{key}.liquidation_threshold", lt - 0.05, min(lt + 0.03, 0.99))))
        elif kind == "morpho_blue_market":
            lltv = float(market["lltv"])
            rows.append(Range(Assumption(f"{key} LLTV", "market", f"{key}.lltv", lltv - 0.05, min(lltv + 0.03, 0.99))))
        elif kind == "pendle_pt_market":
            apy = float(market["pt_implied_apy"])
            rows.append(Range(Assumption(f"{key} PT implied APY", "market", f"{key}.pt_implied_apy", max(apy - 0.03, 0.0), apy + 0.03)))
    for vid, venue in snapshot.venues.items():
        quoted = bool(venue.curve) or snapshot.sources.get(f"venue:{vid}") in ("observed", "derived", "verified")
        low, high = (0.8, 1.25) if quoted else (0.5, 2.0)
        rows.append(Range(Assumption(f"{vid} depth{' (quoted)' if quoted else ' (assumed)'}", "venue_depth", vid, low, high), log=True))
    if sid == "liquidation_cascade":
        a = request.param("arbitrage_absorption_pct", 0.0)
        rows.append(Range(Assumption("arbitrage absorption between rounds", "param", "arbitrage_absorption_pct",
                                     max(a - 0.3, 0.0), min(a + 0.15, 1.0))))
    return rows


def _draw(rng: random.Random, r: Range) -> float:
    lo, hi = r.assumption.low, r.assumption.high
    if r.log and lo > 0 and hi > 0:
        return math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * rng.random())
    return lo + (hi - lo) * rng.random()


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    pos = q * (len(sorted_values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _summary(values: list[float], base: float) -> dict:
    ordered = sorted(values)
    out = {f"p{int(q * 100):02d}_usd": _quantile(ordered, q) for q in PERCENTILES}
    out.update({"min_usd": ordered[0], "max_usd": ordered[-1], "base_usd": base})
    return out


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0


def uncertainty(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, draws: int = DRAWS, seed: int = SEED) -> dict:
    run = scenarios.get(request.scenario_id)
    ranges = model_assumptions(snapshot, request)
    base = run(portfolio, snapshot, request)
    base_positions = {i.position_id: sum(i.loss_components.values()) for i in base.impacts}

    rng = random.Random(seed)
    totals: list[float] = []
    positions: dict[str, list[float]] = {pid: [] for pid in base_positions}
    drawn: dict[str, list[float]] = {r.assumption.label: [] for r in ranges}
    liquidations: list[int] = []
    for _ in range(draws):
        s, r = snapshot, request
        for rg in ranges:
            value = _draw(rng, rg)
            drawn[rg.assumption.label].append(value)
            s, r = _apply(s, r, rg.assumption, value)
        outcome = run(portfolio, s, r)
        totals.append(total_loss(outcome))
        for impact in outcome.impacts:
            positions[impact.position_id].append(sum(impact.loss_components.values()))
        liquidations.append(sum(1 for i in outcome.impacts if i.risk_metric and i.risk_metric["liquidatable"]))

    lo, hi = min(totals), max(totals)
    bins = 15
    width = (hi - lo) / bins if hi > lo else 1.0
    counts = [0] * bins
    for t in totals:
        counts[min(int((t - lo) / width), bins - 1) if hi > lo else 0] += 1
    drivers = sorted(
        ({"assumption": label, "low": rg.assumption.low, "high": rg.assumption.high,
          "rank_correlation": _spearman(drawn[label], totals)}
         for rg in ranges for label in [rg.assumption.label]),
        key=lambda d: abs(d["rank_correlation"]), reverse=True)
    return {
        "draws": draws,
        "seed": seed,
        "method": "uniform draws of unverified model assumptions within their ranges; scenario parameters fixed",
        "portfolio": _summary(totals, total_loss(base)),
        "positions": {pid: _summary(values, base_positions[pid]) for pid, values in positions.items()},
        "histogram": [{"from_usd": lo + i * width, "to_usd": lo + (i + 1) * width, "draws": c} for i, c in enumerate(counts)],
        "liquidatable_positions_share": {str(n): liquidations.count(n) / draws for n in sorted(set(liquidations))},
        "drivers": drivers,
        "fixed_because_verified": [key for key, m in snapshot.markets.items() if m.get("verified")],
    }


def position_curves(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> dict | None:
    """Loss of each position along the scenario's main severity axis (the x axis of the default grid)."""
    from backend.risk.analytics.sensitivity import DEFAULT_GRIDS

    spec = DEFAULT_GRIDS.get(request.scenario_id)
    if spec is None:
        return None
    x_param, xs = spec[0], spec[1]
    run = scenarios.get(request.scenario_id)
    curves: dict[str, list[float]] = {p.position_id: [] for p in portfolio.positions}
    totals = []
    for x in xs:
        outcome = run(portfolio, snapshot, ScenarioRequest(**{**request.__dict__, "parameters": {**request.parameters, x_param: x}}))
        totals.append(total_loss(outcome))
        for impact in outcome.impacts:
            curves[impact.position_id].append(sum(impact.loss_components.values()))
    return {"x_param": x_param, "x_values": list(xs), "positions_usd": curves, "total_usd": totals}
