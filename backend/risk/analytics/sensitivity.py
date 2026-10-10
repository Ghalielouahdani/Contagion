"""Sensitivity: which assumptions drive the result, and how the loss surface looks.

- tornado: move one assumption at a time to a low and a high value, measure the scenario
  loss, rank assumptions by swing. Answers "your assumptions are wrong, so what?".
- grid: scenario loss and number of liquidatable positions over any two scenario
  parameters (heatmap for the UI). A scenario run takes ~50 µs, so grids stay interactive.

Tornado specs are built per scenario from the portfolio and snapshot actually loaded, so a
new market or venue is covered without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.risk.analytics.runner import NEUTRAL_DEPEG, run, total_loss
from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot


@dataclass(frozen=True)
class Assumption:
    label: str
    kind: str  # "param" (scenario parameter), "market" (snapshot market field), "venue_depth" (depth multiplier)
    target: str  # parameter name | "<position_id>.<field>" | venue id
    low: float
    high: float


def _apply(snapshot: Snapshot, request: ScenarioRequest, a: Assumption, value: float) -> tuple[Snapshot, ScenarioRequest]:
    if a.kind == "param":
        return snapshot, replace(request, parameters={**request.parameters, a.target: value})
    if a.kind == "market":
        pid, field = a.target.split(".", 1)
        markets = {**snapshot.markets, pid: {**snapshot.markets[pid], field: str(value)}}
        return replace(snapshot, markets=markets), request
    if a.kind == "venue_depth":
        venue = snapshot.venues[a.target]
        venues = {**snapshot.venues, a.target: replace(venue, effective_depth_usd=venue.effective_depth_usd * value)}
        return replace(snapshot, venues=venues), request
    raise ValueError(f"unknown assumption kind {a.kind!r}")


def _market_assumptions(snapshot: Snapshot) -> list[Assumption]:
    rows = []
    for pid, m in snapshot.markets.items():
        kind = m.get("market_kind")
        if kind == "aave_v3_reserve":
            lt = float(m["liquidation_threshold"])
            rows.append(Assumption(f"{pid} liquidation threshold", "market", f"{pid}.liquidation_threshold", lt - 0.05, lt + 0.03))
        elif kind == "morpho_blue_market":
            lltv = float(m["lltv"])
            rows.append(Assumption(f"{pid} LLTV", "market", f"{pid}.lltv", lltv - 0.05, min(lltv + 0.03, 0.99)))
        elif kind == "pendle_pt_market":
            apy = float(m["pt_implied_apy"])
            rows.append(Assumption(f"{pid} PT implied APY", "market", f"{pid}.pt_implied_apy", max(apy - 0.03, 0.0), apy + 0.03))
    return rows


def _depeg_rows(request: ScenarioRequest, oracle_override: bool = True) -> list[Assumption]:
    shock = request.param("usde_spot_shock_pct", 0.0)
    rows = [
        Assumption("USDe depeg size", "param", "usde_spot_shock_pct", shock * 0.5, shock * 2),
        Assumption("sUSDe beta to USDe", "param", "susde_market_beta", 0.5, 1.5),
        Assumption("Oracle pass-through (all markets)", "param", "oracle_pass_through_override", 0.0, 1.0),
        Assumption("PT implied yield shock", "param", "pt_implied_apy_shock", 0.0, 0.06),
        Assumption("USDe backing loss", "param", "backing_impairment_pct", 0.0, -0.05),
        Assumption("sUSDe exchange-rate cut", "param", "susde_rate_cut_pct", 0.0, -0.05),
    ]
    return rows if oracle_override else [a for a in rows if a.target != "oracle_pass_through_override"]


def _liquidity_rows(snapshot: Snapshot, request: ScenarioRequest) -> list[Assumption]:
    reduction = request.param("exit_liquidity_reduction_pct", 0.0)
    return [
        Assumption("Liquidity lost in the crisis", "param", "exit_liquidity_reduction_pct", reduction * 0.75, min(reduction * 1.15, 0.99)),
    ] + [
        Assumption(f"{vid} depth", "venue_depth", vid, 2.0, 0.5) for vid in snapshot.venues
    ]


def assumptions_for(snapshot: Snapshot, request: ScenarioRequest) -> list[Assumption]:
    sid = request.scenario_id
    if sid == "usde_depeg":
        rows = _depeg_rows(request)
    elif sid == "liquidity_crisis":
        rows = _liquidity_rows(snapshot, request) + [
            Assumption("Fundamental value shock", "param", "fundamental_value_shock_pct", 0.0, -0.05),
        ]
    elif sid == "combined_crisis":
        rows = _depeg_rows(request) + _liquidity_rows(snapshot, request)
    elif sid == "governance_change":
        shift = request.param("liquidation_threshold_shift", 0.0)
        rows = _depeg_rows(request, oracle_override=False) + [
            Assumption("Liquidation threshold shift", "param", "liquidation_threshold_shift", 0.0, min(shift * 2, -0.05)),
            Assumption("Oracle pass-through after the switch", "param", "oracle_switch_pass_through", 0.0, 1.0),
        ]
    elif sid == "carry_squeeze":
        borrow = request.param("borrow_apy_override")
        rows = [
            Assumption("sUSDe APY", "param", "susde_apy", 0.10, -0.05),
            Assumption("Borrow APY", "param", "borrow_apy_override", 0.05, max((borrow or 0.0) * 2, 0.30)),
            Assumption("PT implied yield shock", "param", "pt_implied_apy_shock", -0.03, 0.03),
        ]
    elif sid == "node_shock":
        loss = request.param("loss_pct", 0.0)
        rows = [
            Assumption("Loss at the shocked node", "param", "loss_pct", loss * 0.5, min(loss * 2, 1.0)),
            Assumption("Oracle pass-through (all markets)", "param", "oracle_pass_through_override", 0.0, 1.0),
        ]
    else:
        rows = []
    return rows + _market_assumptions(snapshot)


def liquidatable_count(outcome: ScenarioOutcome) -> int:
    return sum(1 for i in outcome.impacts if i.risk_metric and i.risk_metric["liquidatable"])


def tornado(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> list[dict]:
    base = total_loss(run(portfolio, snapshot, request))
    rows = []
    for a in assumptions_for(snapshot, request):
        losses = []
        for value in (a.low, a.high):
            s, r = _apply(snapshot, request, a, value)
            losses.append(total_loss(run(portfolio, s, r)))
        rows.append({
            "assumption": a.label,
            "target": a.target,
            "low_value": a.low,
            "high_value": a.high,
            "loss_at_low_usd": losses[0],
            "loss_at_high_usd": losses[1],
            "swing_usd": abs(losses[1] - losses[0]),
            "base_loss_usd": base,
        })
    return sorted(rows, key=lambda row: row["swing_usd"], reverse=True)


def grid(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest,
         x_param: str, x_values: list[float], y_param: str, y_values: list[float]) -> dict:
    allowed = set(request.parameters) | (set(NEUTRAL_DEPEG) if request.scenario_id in ("usde_depeg", "combined_crisis") else set())
    for name in (x_param, y_param):
        if name not in allowed:
            raise KeyError(f"{name!r} is not a parameter of scenario {request.scenario_id!r}; allowed: {sorted(allowed)}")
    losses, counts = [], []
    for y in y_values:
        row_loss, row_count = [], []
        for x in x_values:
            outcome = run(portfolio, snapshot, request, **{x_param: x, y_param: y})
            row_loss.append(total_loss(outcome))
            row_count.append(liquidatable_count(outcome))
        losses.append(row_loss)
        counts.append(row_count)
    return {
        "x_param": x_param,
        "x_values": list(x_values),
        "y_param": y_param,
        "y_values": list(y_values),
        "loss_usd": losses,  # loss_usd[i][j] at y_values[i], x_values[j]
        "liquidatable_positions": counts,
    }


DEPEG_AXIS = [-i / 100 for i in range(0, 42, 2)]

# Per scenario: (x parameter, x values, y parameter, y values).
DEFAULT_GRIDS = {
    "usde_depeg": ("usde_spot_shock_pct", DEPEG_AXIS, "oracle_pass_through_override", [0.0, 0.25, 0.5, 0.75, 1.0]),
    "liquidity_crisis": ("exit_liquidity_reduction_pct", [i / 20 for i in range(0, 20)],
                         "fundamental_value_shock_pct", [0.0, -0.02, -0.05, -0.10]),
    "combined_crisis": ("usde_spot_shock_pct", DEPEG_AXIS, "exit_liquidity_reduction_pct", [0.0, 0.25, 0.5, 0.75, 0.9]),
    "governance_change": ("usde_spot_shock_pct", DEPEG_AXIS, "liquidation_threshold_shift", [0.0, -0.025, -0.05, -0.075, -0.10]),
    "carry_squeeze": ("borrow_apy_override", [i / 20 for i in range(0, 21)], "susde_apy", [0.10, 0.07, 0.03, 0.0, -0.05]),
    "node_shock": ("loss_pct", [i / 20 for i in range(0, 20)], "oracle_pass_through_override", [0.0, 0.5, 1.0]),
}


def default_grid(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> dict | None:
    spec = DEFAULT_GRIDS.get(request.scenario_id)
    if spec is None:
        return None
    x_param, xs, y_param, ys = spec
    return grid(portfolio, snapshot, request, x_param, xs, y_param, ys)
