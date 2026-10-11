"""Recompute a fixture set's risk outputs from its inputs, so stored results never drift from the engine.

Usage: python -m backend.risk.regenerate contracts/fixtures/<set> [--no-surface] [--crisis-only]

For every scenario_request<suffix>.json: risk_result<suffix>.json = simulate(portfolio, snapshot,
request, graph) and risk_analytics<suffix>.json = analyze(...) at the preset (offline pages show the
analytics of every scenario), declared in the manifest. Then risk_surface.json. Golden sets (manifest
"golden": true) hold hand-derived expectations: their existing results are never overwritten,
only missing ones are added.

Also writes crisis_plan<suffix>.json: P3's crisis verdict for each preset (scenario assumed to happen),
so the dashboard's Decision page works offline. Dashboard artifacts, not schema v1 contracts: they are
not listed in the manifest. --crisis-only rewrites just these.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.risk import simulate
from backend.risk.analytics import analyze
from backend.risk.surface import main as build_surface


def crisis_plans(folder: Path) -> None:
    from backend.execution.crisis import crisis_plan

    load = lambda name: json.loads((folder / f"{name}.json").read_text())  # noqa: E731
    portfolio, snapshot = load("portfolio"), load("market_snapshot")
    for request_file in sorted(folder.glob("scenario_request*.json")):
        suffix = request_file.stem.removeprefix("scenario_request")
        risk_file = folder / f"risk_result{suffix}.json"
        risk = json.loads(risk_file.read_text()) if risk_file.exists() else None
        plan = crisis_plan(portfolio, snapshot, load(request_file.stem), risk, include_strategies=True)
        (folder / f"crisis_plan{suffix}.json").write_text(json.dumps(plan, indent=2) + "\n")


def regenerate(folder: Path, surface: bool = True) -> None:
    load = lambda name: json.loads((folder / f"{name}.json").read_text())  # noqa: E731
    manifest = load("manifest")
    portfolio, snapshot, graph = load("portfolio"), load("market_snapshot"), load("dependency_graph")
    for request_file in sorted(folder.glob("scenario_request*.json")):
        request_name = request_file.stem
        result_name = request_name.replace("scenario_request", "risk_result")
        manifest["files"].setdefault(request_name, {"path": f"{request_name}.json", "schema": "../../schemas/v1/scenario_request.schema.json"})
        analytics_name = request_name.replace("scenario_request", "risk_analytics")
        if not (manifest.get("golden") and (folder / f"{analytics_name}.json").exists()):
            analytics = analyze(portfolio, snapshot, load(request_name))
            (folder / f"{analytics_name}.json").write_text(json.dumps(analytics, indent=2) + "\n")
            manifest["files"][analytics_name] = {"path": f"{analytics_name}.json", "schema": "../../schemas/v1/risk_analytics.schema.json"}
        if manifest.get("golden") and (folder / f"{result_name}.json").exists():
            continue
        result = simulate(portfolio, snapshot, load(request_name), graph)
        (folder / f"{result_name}.json").write_text(json.dumps(result, indent=2) + "\n")
        manifest["files"][result_name] = {"path": f"{result_name}.json", "schema": "../../schemas/v1/risk_result.schema.json"}
        print(f"{folder.name}/{result_name}: {result['scenario_id']} loss {result['portfolio']['total_conditional_loss_usd']}")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    crisis_plans(folder)
    if surface:
        build_surface(str(folder))


if __name__ == "__main__":
    if "--crisis-only" in sys.argv:
        crisis_plans(Path(sys.argv[1]))
    else:
        regenerate(Path(sys.argv[1]), surface="--no-surface" not in sys.argv)
