"""Factor exposure: how many dollars each risk factor really moves, versus NAV.

Answers "am I diversified?": four protocols can still be one factor. Effective leverage on a
factor = dollar exposure to that factor / net equity (NAV).
"""

from __future__ import annotations

from backend.risk.analytics.runner import neutral_depeg, position_loss, run
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

# factor -> (scenario parameter, probe move, unit of the reported sensitivity)
FACTORS = {
    "usde_price": ("usde_spot_shock_pct", -0.01, "per 1% USDe price drop"),
    "usde_backing": ("backing_impairment_pct", -0.01, "per 1% USDe backing loss"),
    "susde_exchange_rate": ("susde_rate_cut_pct", -0.01, "per 1% sUSDe rate cut"),
    "pt_implied_yield": ("pt_implied_apy_shock", 0.01, "per +100bp PT implied yield"),
}


def factor_exposures(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, nav: float) -> list[dict]:
    base = neutral_depeg(request)
    rows = []
    for factor, (param, move, unit) in FACTORS.items():
        outcome = run(portfolio, snapshot, base, **{param: move})
        by_position = {p.position_id: position_loss(outcome, p.position_id) for p in portfolio.positions}
        loss = sum(by_position.values())
        exposure = loss / abs(move)  # dollars lost per 100% move: the factor's notional exposure
        rows.append({
            "factor": factor,
            "loss_usd": loss,
            "unit": unit,
            "exposure_usd": exposure,
            "effective_leverage": exposure / nav,
            "positions_exposed": sorted(pid for pid, v in by_position.items() if v > 1e-6),
            "loss_by_position_usd": by_position,
        })
    return rows
