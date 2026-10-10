"""Precomputed risk surface: engine results over a grid of slider values, for an offline demo.

The dashboard must run without a network (blueprint section 16, P4). With this file the
fixture mode stays live: each slider position maps to a real engine result, not a scaled
fixture. Contagion blocks are left out (they do not depend on the shock size); the
frontend takes them from the set's risk_result files.

Usage: python -m backend.risk.surface contracts/fixtures/<set>
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from backend.execution.integration import decide
from backend.risk import simulate

DEPEG_SHOCKS = [-i / 100 for i in range(0, 41)]  # 0% .. -40%
LIQUIDITY_LOSSES = [i / 20 for i in range(0, 20)]  # 0% .. 95%

# scenario_id -> (request file in the set, slider parameter, values). One live slider per
# scenario offline; the other parameters keep the request's values. Missing files are skipped.
SLIDERS = {
    "usde_depeg": ("scenario_request", "usde_spot_shock_pct", DEPEG_SHOCKS),
    "liquidity_crisis": ("scenario_request_liquidity", "exit_liquidity_reduction_pct", LIQUIDITY_LOSSES),
    "combined_crisis": ("scenario_request_combined", "usde_spot_shock_pct", DEPEG_SHOCKS),
    "governance_change": ("scenario_request_governance", "usde_spot_shock_pct", DEPEG_SHOCKS),
    "carry_squeeze": ("scenario_request_carry", "borrow_apy_override", [i / 20 for i in range(0, 21)]),  # 0% .. 100%
    "node_shock": ("scenario_request_node_shock", "loss_pct", [i / 20 for i in range(0, 11)]),  # 0% .. 50%
    "liquidation_cascade": ("scenario_request_cascade", "usde_spot_shock_pct", DEPEG_SHOCKS),
}


def _point(portfolio: dict, snapshot: dict, request: dict, param: str, value: float) -> dict:
    r = copy.deepcopy(request)
    r["scenario"]["parameters"][param] = f"{value:.2f}"
    result = simulate(portfolio, snapshot, r)
    result.pop("contagion", None)
    # Calculation traces are kept: offline, every slider value shows how its numbers were computed.
    return {
        "value": f"{value:.2f}",
        "risk_result": result,
        "decisions": {p["position_id"]: decide(portfolio, snapshot, r, p["position_id"], result) for p in portfolio["positions"]},
    }


def build(portfolio: dict, snapshot: dict, requests: dict[str, dict]) -> dict:
    """requests: scenario_id -> base scenario request (scenarios without one are skipped)."""
    scenarios = {}
    for scenario_id, (_, param, values) in SLIDERS.items():
        request = requests.get(scenario_id)
        if request is None:
            continue
        scenarios[scenario_id] = {
            "param": param,
            "base_request_id": request["request_id"],
            "points": [_point(portfolio, snapshot, request, param, v) for v in values],
        }
    return {
        "schema_version": "1.0",
        "surface_id": f"surface_{snapshot['snapshot_id']}",
        "portfolio_id": portfolio["portfolio_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "scenarios": scenarios,
    }


def main(folder: str) -> None:
    root = Path(folder)
    load = lambda name: json.loads((root / f"{name}.json").read_text())  # noqa: E731
    requests = {sid: load(file) for sid, (file, _, _) in SLIDERS.items() if (root / f"{file}.json").is_file()}
    surface = build(load("portfolio"), load("market_snapshot"), requests)
    (root / "risk_surface.json").write_text(json.dumps(surface, separators=(",", ":")) + "\n")
    manifest = load("manifest")
    manifest["files"]["risk_surface"] = {"path": "risk_surface.json", "schema": "../../schemas/v1/risk_surface.schema.json"}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{root / 'risk_surface.json'}: {(root / 'risk_surface.json').stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1])
