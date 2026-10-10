"""Risk engine entry point (owner: P2).

portfolio + market_snapshot + scenario_request (+ dependency_graph) -> risk_result, all as
schema v1 contract dicts. Deterministic: same inputs, same output.
"""

from __future__ import annotations

from backend.risk import contagion, scenarios
from backend.risk.graph import Graph
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot
from backend.risk.report import build_risk_result


def simulate(portfolio: dict, snapshot: dict, request: dict, graph: dict | None = None) -> dict:
    p = Portfolio.from_contract(portfolio)
    s = Snapshot.from_contract(snapshot)
    r = ScenarioRequest.from_contract(request)
    _check_ids(p, s, r, graph)
    outcome = scenarios.get(r.scenario_id)(p, s, r)
    contagion.annotate(outcome, Graph.from_contract(graph) if graph is not None else None, p, s, r)
    return build_risk_result(r, s, outcome)


def _check_ids(p: Portfolio, s: Snapshot, r: ScenarioRequest, graph: dict | None) -> None:
    mismatches = []
    if r.portfolio_id != p.portfolio_id:
        mismatches.append(f"request.portfolio_id={r.portfolio_id!r} but portfolio is {p.portfolio_id!r}")
    if r.snapshot_id != s.snapshot_id:
        mismatches.append(f"request.snapshot_id={r.snapshot_id!r} but snapshot is {s.snapshot_id!r}")
    if graph is not None and r.graph_id != graph.get("graph_id"):
        mismatches.append(f"request.graph_id={r.graph_id!r} but graph is {graph.get('graph_id')!r}")
    if mismatches:
        raise ValueError("; ".join(mismatches))
