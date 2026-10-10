"""Build one synthetic stress portfolio from recorded, verified Ethereum markets.

No wallet balances are claimed. Market observations retain their original evidence;
the composed snapshot deliberately has no single block number.
Run: python -m backend.discovery.build_stress_portfolio
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

from backend.discovery.service import revalue_portfolio
from backend.discovery.validation import consistency_errors, schema_errors
from backend.risk.regenerate import regenerate

ROOT = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
SET = "stress_portfolio_01"


def build() -> Path:
    def read(source: str, name: str) -> dict:
        return json.loads((ROOT / source / f"{name}.json").read_text())

    sources = ["verified_2026_10_10", "verified_lending_2026_10_10"]
    portfolios = [read(s, "portfolio") for s in sources]
    snapshots = [read(s, "market_snapshot") for s in sources]
    graphs = [read(s, "dependency_graph") for s in sources]
    warning = (
        "Synthetic allocations on real Ethereum markets; not an imported wallet. "
        "Recorded observations from blocks 26161879 and 26162896 are composed for stress testing; "
        "this is not a fresh or single-block snapshot. Edge evidence retains observation times."
    )
    portfolio = copy.deepcopy(portfolios[0])
    portfolio["portfolio_id"] = SET
    portfolio["positions"].extend(copy.deepcopy(portfolios[1]["positions"]))
    positions = {p["position_id"]: p for p in portfolio["positions"]}
    positions["ethena_susde_01"]["quantity"] = "400000"
    positions["aave_01"].update(collateral_quantity="1000000", debt_quantity="820000")
    positions["morpho_01"]["collateral_quantity"] = "400000"
    prices = {**snapshots[0]["prices_usd"], **snapshots[1]["prices_usd"]}
    positions["morpho_01"]["debt_quantity"] = str(
        (Decimal("400000") * Decimal(prices["sUSDe"]["value"]) * Decimal("0.88")
         / Decimal(prices["PYUSD"]["value"])).quantize(Decimal("0.01"))
    )
    positions["pendle_01"]["quantity"] = "300000"
    positions["lend_susde_01"]["quantity"] = "1000000"
    positions["lend_usde_01"]["quantity"] = "500000"

    snapshot = copy.deepcopy(snapshots[0])
    snapshot.update(snapshot_id=f"snapshot_{SET}", as_of=max(s["as_of"] for s in snapshots), block_number=None)
    for key in ("prices_usd", "exchange_rates", "markets", "yields", "exit_venues"):
        snapshot[key].update(copy.deepcopy(snapshots[1][key]))
    snapshot["warnings"] = list(dict.fromkeys([warning, *snapshots[0]["warnings"], *snapshots[1]["warnings"]]))
    portfolio, valuation_warnings = revalue_portfolio(portfolio, snapshot)
    if valuation_warnings:
        raise ValueError(valuation_warnings)

    graph = copy.deepcopy(graphs[0])
    graph.update(graph_id=f"graph_{SET}", portfolio_id=SET, as_of=snapshot["as_of"])
    nodes = {n["id"]: copy.deepcopy(n) for n in graphs[0]["nodes"]}
    for node in graphs[1]["nodes"]:
        if node["id"] not in nodes:
            nodes[node["id"]] = copy.deepcopy(node)
    for pid, position in positions.items():
        node = nodes[f"position:{pid}"]
        node.setdefault("attributes", {}).update(position)
    graph["nodes"] = list(nodes.values())
    edges, seen = [], set()
    for original in graphs:
        for edge in original["edges"]:
            key = (edge["source"], edge["target"], edge["relation"], edge["risk_channel"])
            if key in seen:
                continue
            seen.add(key)
            item = copy.deepcopy(edge)
            item["id"] = f"edge:stress_{len(edges) + 1}"
            edges.append(item)
    graph["edges"] = edges
    graph["warnings"] = list(dict.fromkeys([warning, *graphs[0]["warnings"], *graphs[1]["warnings"]]))
    problems = consistency_errors(portfolio, graph, snapshot)
    for name, data in (("portfolio", portfolio), ("dependency_graph", graph), ("market_snapshot", snapshot)):
        problems.extend(schema_errors(data, f"{name}.schema.json"))
    if problems:
        raise ValueError(problems)

    folder = ROOT / SET
    folder.mkdir(exist_ok=True)
    manifest = {
        "schema_version": "1.0", "fixture_set_id": SET, "golden": False,
        "description": warning,
        "ids": {"portfolio_id": SET, "graph_id": graph["graph_id"], "snapshot_id": snapshot["snapshot_id"]},
        "files": {},
    }

    def write(name: str, data: dict) -> None:
        (folder / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
        manifest["files"][name] = {"path": f"{name}.json", "schema": f"../../schemas/v1/{name}.schema.json"}

    for name, data in (("portfolio", portfolio), ("dependency_graph", graph), ("market_snapshot", snapshot)):
        write(name, data)
    for path in sorted((ROOT / sources[0]).glob("scenario_request*.json")):
        request = json.loads(path.read_text())
        request.update(request_id=f"{SET}_{path.stem}", portfolio_id=SET,
                       graph_id=graph["graph_id"], snapshot_id=snapshot["snapshot_id"])
        if request["scenario"]["scenario_id"] == "carry_squeeze":
            request["scenario"]["horizon_days"] = 30
        write(path.stem, request)
        manifest["files"][path.stem]["schema"] = "../../schemas/v1/scenario_request.schema.json"
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    regenerate(folder)
    return folder


if __name__ == "__main__":
    print(build())
