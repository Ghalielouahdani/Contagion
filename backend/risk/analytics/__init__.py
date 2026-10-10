"""Risk analytics: the dollar value the engine creates for the fund.

analyze(portfolio, snapshot, request) -> risk_analytics contract dict, with a headline of
money numbers and the four analyses behind them:
- factor_exposure: the real concentration behind "diversified" protocols;
- breaking_points: the shock sizes at which positions are liquidated or NAV is hit;
- derisking: targeted vs uniform de-risking cost for the same protection;
- liquidation_protection: deleveraging cost vs liquidation penalty avoided;
- sensitivity: tornado of assumptions and a loss / liquidation heatmap.
All values are conditional on the scenario and the snapshot assumptions, never probabilities.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from backend.risk.analytics import breaking_points, derisking, exposure, liquidation, sensitivity, uncertainty
from backend.risk.analytics.runner import run, total_loss
from backend.risk.engine import _check_ids
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

ASSUMPTIONS = [
    "Conditional on the scenario: losses and savings are what happens if it occurs, not expected values.",
    "Exit costs use venue fee, gas and the constant-product depth proxy from the snapshot; replace with executable quotes when available.",
    "De-risking exits happen before the scenario at normal depth; pro-rata exits keep HF/LTV unchanged.",
    "Liquidation penalty = close-factor share of debt x protocol incentive (Aave 50% above HF 0.95, Morpho 100%).",
]


def analyze(portfolio: dict, snapshot: dict, request: dict, target_loss_reduction_pct: float = 0.5) -> dict:
    p = Portfolio.from_contract(portfolio)
    s = Snapshot.from_contract(snapshot)
    r = ScenarioRequest.from_contract(request)
    _check_ids(p, s, r, None)

    nav = sum(pos.net_equity_usd for pos in p.positions)
    outcome = run(p, s, r)
    scenario_loss = total_loss(outcome)

    factors = exposure.factor_exposures(p, s, r, nav)
    legs = derisking.build_legs(p, s, outcome, r.horizon_days)
    plan = derisking.compare(legs, s, nav, target_loss_reduction_pct)
    protection = liquidation.protection(p, s, outcome, r.horizon_days, r.param("oracle_lag_hours", 0.0) or 0.0)
    usde = next(f for f in factors if f["factor"] == "usde_price")
    tornado = sensitivity.tornado(p, s, r)

    warnings = []
    if not s.verified:
        warnings.append("Computed from unverified market parameters; illustrative, never a real-market result.")
    if any(i.insufficient_data for i in outcome.impacts):
        warnings.append("Some positions lack data; their contribution is excluded where it could not be computed.")

    result = {
        "schema_version": "1.0",
        "analytics_id": f"analytics_{r.request_id}",
        "request_id": r.request_id,
        "portfolio_id": r.portfolio_id,
        "scenario_id": r.scenario_id,
        "horizon_days": r.horizon_days,
        "currency": "USD",
        "headline": {
            "nav_usd": nav,
            "scenario_loss_usd": scenario_loss,
            "scenario_loss_pct_nav": scenario_loss / nav,
            "usde_exposure_usd": usde["exposure_usd"],
            "usde_effective_leverage": usde["effective_leverage"],
            "derisking_savings_usd": plan["savings_usd"],
            "derisking_savings_bps_nav": plan["savings_bps_nav"],
            "liquidation_protection_net_benefit_usd": sum(
                (row["preemptive"]["net_benefit_usd"] for row in protection if row["preemptive"]), 0.0
            ),
            "targeted_plan_break_even_probability": plan["targeted"]["break_even_probability"],
            "top_risk_driver": tornado[0]["assumption"] if tornado else None,
        },
        "factor_exposure": factors,
        "breaking_points": {
            "liquidation": breaking_points.liquidation_points(p, s, r),
            "nav_drawdown": breaking_points.nav_drawdown_points(p, s, r, nav),
        },
        "derisking": plan,
        "liquidation_protection": protection,
        "sensitivity": {"tornado": tornado, "grid": sensitivity.default_grid(p, s, r)},
        "uncertainty": uncertainty.uncertainty(p, s, r),
        "position_curves": uncertainty.position_curves(p, s, r),
        "assumptions": ASSUMPTIONS,
        "warnings": warnings,
    }
    return _format(result)


def _format(value, key: str = ""):
    """Floats become decimal strings: 2 dp for *_usd fields (and dicts of them), 4 dp otherwise."""
    if isinstance(value, dict):
        return {k: _format(v, k if not key.endswith("_usd") else key) for k, v in value.items()}
    if isinstance(value, list):
        return [_format(v, key) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    quantum = Decimal("0.01") if key.endswith("_usd") else Decimal("0.0001")
    return str(Decimal(repr(float(value))).quantize(quantum, ROUND_HALF_UP))
