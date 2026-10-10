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
    value = Decimal(repr(float(x))).quantize(CENT, ROUND_HALF_UP)
    return value if value else abs(value)  # never publish "-0.00" (float noise around zero)


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
    total_step = {
        "id": "loss", "label": "Conditional loss of the position", "formula": "sum of the loss components",
        "inputs": [{"name": labelize(k), "value": str(v), "unit": "usd", "source": "derived"} for k, v in components.items()],
        "result": {"value": str(loss), "unit": "usd"},
    }
    row["trace"] = [_step(s) for s in impact.trace] + [total_step]
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
    if outcome.cascade is not None:
        result["cascade"] = _cascade(outcome.cascade)
    aggregation = {
        "id": "portfolio_loss", "label": "Portfolio conditional loss",
        "formula": "sum of position losses + shared exit-venue penalty (computed on the whole portfolio, not per position)",
        "inputs": [{"name": row["position_id"], "value": row["conditional_loss_usd"], "unit": "usd", "source": "derived"}
                   for row in rows] + [{"name": "shared exit-venue penalty", "value": str(penalty), "unit": "usd", "source": "derived"}],
        "result": {"value": str(total) if complete else None, "unit": "usd"},
    }
    if complete and net_before:
        aggregation["note"] = f"{total / net_before:.2%} of net equity ({net_before} USD)."
    result["trace"] = [_step(s) for s in outcome.trace] + [aggregation]
    if outcome.comparison is not None:
        runs = [(run, money(run["total_loss"])) for run in outcome.comparison["runs"]]
        result["comparison"] = {
            "runs": [
                {"run_id": run["run_id"], "description": run["description"], "total_conditional_loss_usd": str(loss)}
                for run, loss in runs
            ],
            # Published total minus the reference runs, from rounded figures so it reconciles to the cent.
            "excess_loss_usd": str(total - sum((loss for _, loss in runs), Decimal(0))) if complete else None,
            "excess_meaning": outcome.comparison["excess_meaning"],
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


def _cascade(c: dict) -> dict:
    moves = lambda m: {k: str(ratio(v)) for k, v in m.items()}
    return {
        "initial_moves": moves(c["initial_moves"]),
        "final_moves": moves(c["final_moves"]),
        "trough_moves": moves(c["trough_moves"]),
        "amplification": None if c["amplification"] is None else str(ratio(c["amplification"])),
        "rounds": [{"round": r["round"], "liquidated_debt_usd": str(money(r["liquidated_debt_usd"])),
                    "collateral_sold_usd": str(money(r["collateral_sold_usd"])), "moves": moves(r["moves"])}
                   for r in c["rounds"]],
        "liquidated_debt_usd": str(money(c["liquidated_debt"])),
        "bad_debt_usd": str(money(c["bad_debt"])),
        "stuck_debt_usd": str(money(c["stuck_debt"])),
        "converged": c["converged"],
    }


SIX = Decimal("0.000001")


def _value(value, unit: str):
    if value is None or isinstance(value, (bool, str)):
        return value
    x = float(value)
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return str(money(x)) if unit == "usd" else str(Decimal(repr(x)).quantize(SIX, ROUND_HALF_UP))


def _step(s: dict) -> dict:
    out = {
        "id": s["id"], "label": s["label"], "formula": s["formula"],
        "inputs": [{**i, "value": _value(i["value"], i["unit"])} for i in s["inputs"]],
        "result": {"value": _value(s["result"]["value"], s["result"]["unit"]), "unit": s["result"]["unit"]},
    }
    if s.get("note"):
        out["note"] = s["note"]
    if s.get("rows"):
        out["rows"] = [{k: _value(v, "usd" if k.endswith("_usd") else "ratio") for k, v in r.items()} for r in s["rows"]]
    return out


def labelize(key: str) -> str:
    return key.replace("_", " ")
