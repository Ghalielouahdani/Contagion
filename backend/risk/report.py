"""Turn unrounded scenario outcomes into the risk_result contract (schema v1).

Rounding happens once, here. Derived totals are computed from the rounded parts, so
the published numbers reconcile to the cent: components sum to the loss, net before
minus loss equals net after, positions plus shared penalty equal the portfolio total.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from backend.risk.model import PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot

MODEL_VERSION = "risk-v0.1"
CENT = Decimal("0.01")
RATIO = Decimal("0.0001")


def money(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(CENT, ROUND_HALF_UP)


def ratio(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(RATIO, ROUND_HALF_UP)


def _position(impact: PositionImpact, status: str) -> tuple[dict, Decimal, Decimal]:
    components = {k: money(v) for k, v in impact.loss_components.items()}
    loss = sum(components.values(), Decimal(0))
    net_before = money(impact.net_before)
    gross_after = money(impact.gross_after)
    executable = None
    if impact.executable_after is not None:
        executable = gross_after - components["execution_haircut"]
    metric = None
    if impact.risk_metric is not None:
        metric = {k: (v if isinstance(v, (bool, str)) else str(ratio(v))) for k, v in impact.risk_metric.items()}
    row = {
        "position_id": impact.position_id,
        "gross_value_before_usd": str(money(impact.gross_before)),
        "gross_value_after_usd": str(gross_after),
        "executable_value_after_usd": None if executable is None else str(executable),
        "debt_after_usd": str(money(impact.debt_after)),
        "net_equity_before_usd": str(net_before),
        "net_equity_after_usd": str(net_before - loss),
        "conditional_loss_usd": str(loss),
        "loss_components": {k: str(v) for k, v in components.items()},
        "risk_metric": metric,
        "source_type": "derived",
        "calculation_status": "insufficient_data" if impact.insufficient_data else status,
        "warnings": impact.warnings,
    }
    if impact.contagion is not None:
        row["contagion"] = impact.contagion
    return row, net_before, loss


def build_risk_result(request: ScenarioRequest, snapshot: Snapshot, outcome: ScenarioOutcome) -> dict:
    status = "computed" if snapshot.verified else "illustrative"
    rows, net_before, total_loss = [], Decimal(0), Decimal(0)
    for impact in outcome.impacts:
        row, nb, loss = _position(impact, status)
        rows.append(row)
        net_before += nb
        total_loss += loss

    penalty = money(outcome.shared_liquidity_penalty)
    complete = not any(i.insufficient_data for i in outcome.impacts)
    total = total_loss + penalty
    warnings = list(outcome.warnings)
    if status == "illustrative":
        warnings.append("Computed from unverified market parameters; illustrative, never a real-market result.")

    result = {
        "schema_version": "1.0",
        "simulation_id": f"result_{request.request_id}",
        "request_id": request.request_id,
        "portfolio_id": request.portfolio_id,
        "scenario_id": request.scenario_id,
        "horizon_days": request.horizon_days,
        "currency": "USD",
        "positions": rows,
        "portfolio": {
            "net_equity_before_usd": str(net_before),
            "net_equity_after_usd": str(net_before - total) if complete else None,
            "total_conditional_loss_usd": str(total) if complete else None,
            "shared_liquidity_penalty_usd": str(penalty),
            "aggregation_status": "complete" if complete else "insufficient_data",
        },
        "provenance": {
            "model_version": MODEL_VERSION,
            "input_snapshot_id": snapshot.snapshot_id,
            "input_graph_id": request.graph_id,
        },
        "warnings": warnings,
    }
    if outcome.contagion is not None:
        result["contagion"] = {
            **outcome.contagion,
            "hubs": [
                {**h, "gross_exposure_usd": str(money(h["gross_exposure_usd"])), "net_equity_usd": str(money(h["net_equity_usd"]))}
                for h in outcome.contagion["hubs"]
            ],
        }
    return result
