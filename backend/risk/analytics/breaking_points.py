"""Reverse stress tests: the shock size at which something breaks.

Instead of "what happens at -5%?", answer "at what level do I lose this position?" and
"at what depeg does the fund lose 10% / 20% of NAV?". Solved by bisection: liquidation
eligibility and losses are monotonic in each shock.
"""

from __future__ import annotations

from typing import Callable

from backend.risk.analytics.runner import neutral_depeg, run, total_loss
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

# mechanism -> scenario parameter (all negative = adverse)
MECHANISMS = {
    "usde_market_depeg": "usde_spot_shock_pct",
    "usde_backing_loss": "backing_impairment_pct",
    "susde_rate_cut": "susde_rate_cut_pct",
}
MAX_SHOCK = 0.99


def _bisect(breaks: Callable[[float], bool], tol: float = 1e-7) -> float | None:
    """Smallest adverse shock size s in (0, MAX_SHOCK] with breaks(s) True; None if never."""
    if not breaks(MAX_SHOCK):
        return None
    lo, hi = 0.0, MAX_SHOCK
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if breaks(mid) else (mid, hi)
    return hi


def liquidation_points(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> list[dict]:
    base = neutral_depeg(request)
    rows = []
    for position in portfolio.positions:
        if not position.is_borrow or snapshot.market(position.position_id) is None:
            continue
        for mechanism, param in MECHANISMS.items():
            def liquidatable(size: float, pid=position.position_id, param=param) -> bool:
                outcome = run(portfolio, snapshot, base, **{param: -size})
                impact = next(i for i in outcome.impacts if i.position_id == pid)
                return bool(impact.risk_metric and impact.risk_metric["liquidatable"])

            size = _bisect(liquidatable)
            rows.append({
                "position_id": position.position_id,
                "mechanism": mechanism,
                "breaks_at_shock_pct": None if size is None else -size,
                "immune": size is None,
            })
    return rows


def nav_drawdown_points(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, nav: float,
                        drawdowns: tuple[float, ...] = (0.10, 0.20, 0.50)) -> list[dict]:
    base = neutral_depeg(request)
    usde0 = snapshot.prices_usd["USDe"]
    rows = []
    for dd in drawdowns:
        size = _bisect(lambda s: total_loss(run(portfolio, snapshot, base, usde_spot_shock_pct=-s)) >= dd * nav)
        rows.append({
            "nav_drawdown_pct": dd,
            "usde_depeg_pct": None if size is None else -size,
            "usde_price": None if size is None else usde0 * (1 - size),
        })
    return rows
