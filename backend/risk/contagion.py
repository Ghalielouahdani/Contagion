"""Contagion paths: explain every loss through the dependency graph, and cross-check both.

Amounts come from valuation (facts: assets held, market parameters). The graph explains
how each shock reaches each position, with evidence and confidence. The two are checked
against each other, never silently trusted:
- graph gap: valuation says a factor hits the position, the graph has no path to it;
- unmodeled exposure: the graph has a path, valuation shows no loss from that factor.
A missing edge therefore never turns into a silent zero loss.

Hubs are what only the graph can see: nodes several positions depend on at once.
"""

from __future__ import annotations

from dataclasses import replace

from backend.risk import scenarios
from backend.risk.graph import CONFIDENCE_RANK, Graph, path_confidence
from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot

EXPOSED_USD = 0.01
PROBE = 0.01  # size of the single-factor probe used to test valuation exposure

# Scenario A factors: scenario parameter, probe value, root node (graph, position -> node id, or None
# when the factor cannot apply to that kind of position).
DEPEG_FACTORS = {
    "usde_price": ("usde_spot_shock_pct", -PROBE, lambda g, p: "asset:USDe"),
    "usde_backing": ("backing_impairment_pct", -PROBE,
                     lambda g, p: "offchain:ethena_backing" if g.has("offchain:ethena_backing") else "asset:USDe"),
    "susde_exchange_rate": ("susde_rate_cut_pct", -PROBE, lambda g, p: "asset:sUSDe"),
    "pt_implied_yield": ("pt_implied_apy_shock", PROBE,
                         lambda g, p: f"market:{p.position_id}" if p.position_type == "pt_holding" else None),
}
NEUTRAL = {"usde_spot_shock_pct": 0.0, "backing_impairment_pct": 0.0, "susde_rate_cut_pct": 0.0, "pt_implied_apy_shock": 0.0}
DEPEG_LIKE = ("usde_depeg", "combined_crisis", "governance_change")  # scenarios that apply the scenario A shocks
EXIT_LIQUIDITY = ("liquidity_crisis", "combined_crisis")

# Carry squeeze factors: parameter, (neutral, probe) values, root node.
CARRY_FACTORS = {
    "susde_yield": ("susde_apy", (0.0, -PROBE), lambda g, p: "asset:sUSDe"),
    "borrow_rate": ("borrow_apy_override", (0.0, PROBE),
                    lambda g, p: f"asset:{p.debt_asset}" if p.is_borrow
                    else f"asset:{p.asset_symbol}" if p.position_type == "lending_supply" else None),
}


def _position_node(position_id: str) -> str:
    return f"position:{position_id}"


def _path_row(graph: Graph, factor: str, root: str, path) -> dict:
    return {
        "factor": factor,
        "root": root,
        "nodes": [path[0].source] + [e.target for e in path],
        "edges": [e.id for e in path],
        "channels": [e.risk_channel for e in path],
        "confidence": path_confidence(path),
        "unverified_edges": [e.id for e in path if e.evidence_status in ("to_verify", "assumed")],
    }


def _depeg_exposures(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> dict[str, dict[str, bool]]:
    """factor -> position_id -> does valuation lose money when only this factor moves?"""
    run = scenarios.get("usde_depeg")
    exposures = {}
    for factor, (param, probe, _) in DEPEG_FACTORS.items():
        probe_request = replace(request, parameters={**request.parameters, **NEUTRAL, param: probe})
        outcome = run(portfolio, snapshot, probe_request)
        exposures[factor] = {i.position_id: abs(sum(i.loss_components.values())) > EXPOSED_USD for i in outcome.impacts}
    return exposures


def _carry_exposures(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> dict[str, dict[str, bool]]:
    """factor -> position_id -> does the carry change when only this rate moves?"""
    run = scenarios.get("carry_squeeze")
    base = {"susde_apy": 0.0, "borrow_apy_override": 0.0, "collateral_supply_apy_override": 0.0, "pt_implied_apy_shock": 0.0}
    exposures = {}
    for factor, (param, (neutral, probe), _) in CARRY_FACTORS.items():
        losses = []
        for value in (neutral, probe):
            outcome = run(portfolio, snapshot, replace(request, parameters={**base, param: value}))
            losses.append({i.position_id: sum(i.loss_components.values()) for i in outcome.impacts})
        exposures[factor] = {pid: abs(losses[1][pid] - losses[0][pid]) > EXPOSED_USD for pid in losses[0]}
    return exposures


def _factor_checks(outcome: ScenarioOutcome, portfolio: Portfolio, snapshot: Snapshot,
                   request: ScenarioRequest) -> list[tuple[str, object, dict[str, bool]]]:
    """(factor, root(graph, position) -> node | None, position_id -> exposed in valuation) for the scenario."""
    sid = request.scenario_id
    if sid in DEPEG_LIKE:
        exposures = _depeg_exposures(portfolio, snapshot, request)
        return [(f, DEPEG_FACTORS[f][2], exposures[f]) for f, (param, _, _) in DEPEG_FACTORS.items()
                if (request.param(param, 0.0) or 0.0) != 0]
    if sid == "carry_squeeze":
        exposures = _carry_exposures(portfolio, snapshot, request)
        return [(f, CARRY_FACTORS[f][2], exposures[f]) for f in CARRY_FACTORS]
    if sid == "node_shock":
        node = request.parameters["node_id"]
        exposed = {i.position_id: abs(sum(i.loss_components.values())) > EXPOSED_USD for i in outcome.impacts}
        return [("node_shock", lambda g, p: node, exposed)]
    return []


def annotate(outcome: ScenarioOutcome, graph: Graph | None, portfolio: Portfolio, snapshot: Snapshot,
             request: ScenarioRequest) -> None:
    if graph is None:
        outcome.contagion = {"graph_id": None, "hubs": [], "warnings": [
            "No dependency graph supplied: losses are not linked to contagion paths."]}
        return

    warnings: list[str] = []
    impacts = {i.position_id: i for i in outcome.impacts}
    checks = _factor_checks(outcome, portfolio, snapshot, request)
    if request.scenario_id == "node_shock" and not graph.has(request.parameters["node_id"]):
        warnings.append(f"{request.parameters['node_id']} is not in the dependency graph: every loss is a graph gap.")

    for position in portfolio.positions:
        node = _position_node(position.position_id)
        impact = impacts[position.position_id]
        block = {"paths": [], "evidence_confidence": None, "graph_gaps": [], "unmodeled_exposures": []}
        if not graph.has(node):
            block["graph_gaps"].append(f"{node} is not in the dependency graph.")
            impact.contagion = block
            continue

        best_per_factor = []
        for factor, root_of, exposures in checks:
            root = root_of(graph, position)
            if root is None:
                continue
            paths = graph.paths(node, root)
            exposed = exposures[position.position_id]
            if exposed and not paths:
                block["graph_gaps"].append(
                    f"Valuation shows {factor} losses but the graph has no path from {node} to {root}: dependency missing from the graph.")
            elif paths and not exposed and position.position_type == "lending_supply":
                # Lender loss is a threshold effect (borrowers must be underwater): modeled, just zero at this size.
                impact.warnings.append(
                    f"Linked to {root} ({factor}) through the graph; no lender loss at this scenario size "
                    "(it starts only once borrowers' collateral stops covering their debt).")
            elif paths and not exposed:
                block["unmodeled_exposures"].append(
                    f"The graph links {node} to {root} ({factor}) but valuation shows no loss from it: exposure not modeled.")
            if paths:
                block["paths"].extend(_path_row(graph, factor, root, p) for p in paths)
                best_per_factor.append(max((path_confidence(p) for p in paths), key=CONFIDENCE_RANK.__getitem__))

        if request.scenario_id in EXIT_LIQUIDITY:
            venues = graph.exits_of(node)
            if position.exit_venue_id not in venues:
                block["graph_gaps"].append(
                    f"Portfolio exits {position.position_id} via {position.exit_venue_id}, but the graph has no exits_via edge to it.")
            for venue in venues:
                for path in graph.paths(node, venue, max_depth=1):
                    block["paths"].append(_path_row(graph, "exit_liquidity", venue, path))
                    best_per_factor.append(path_confidence(path))

        if best_per_factor:
            block["evidence_confidence"] = min(best_per_factor, key=CONFIDENCE_RANK.__getitem__)
        if block["graph_gaps"]:
            impact.warnings.append("Contagion path incomplete in the dependency graph (see contagion.graph_gaps).")
        impact.contagion = block

    outcome.contagion = {"graph_id": graph.graph_id, "hubs": hubs(graph, portfolio), "warnings": warnings}


def hubs(graph: Graph, portfolio: Portfolio) -> list[dict]:
    """Nodes that two or more positions depend on: where one failure hits several lines at once."""
    by_node: dict[str, list] = {}
    for position in portfolio.positions:
        node = _position_node(position.position_id)
        if not graph.has(node):
            continue
        for dep in graph.reachable(node):
            by_node.setdefault(dep, []).append(position)
    rows = [
        {
            "node": node,
            "label": graph.label(node),
            "node_type": graph.nodes[node]["type"] if node in graph.nodes else "unknown",
            "positions": sorted(p.position_id for p in positions),
            "gross_exposure_usd": sum(p.gross_value_usd for p in positions),
            "net_equity_usd": sum(p.net_equity_usd for p in positions),
        }
        for node, positions in by_node.items() if len(positions) >= 2
    ]
    return sorted(rows, key=lambda r: (-len(r["positions"]), -r["net_equity_usd"], r["node"]))
