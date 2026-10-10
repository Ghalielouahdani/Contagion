"""FastAPI orchestration for the dashboard (blueprint section 10).

Serves the routes the frontend already calls (frontend/src/data/api.ts):
- discovery: fixture graph and snapshot of the selected fixture set (P1 live mode pending);
- risk: the live engine, so every slider value is computed, not scaled from a fixture;
- decision: provisional, computed from the risk engine until P3 lands.

Every route takes an optional ?set=<fixture set> (default: env FIXTURE_SET or demo_ethena_01),
e.g. ?set=verified_2026_10_10 for the markets verified on-chain.

Run: .venv/bin/uvicorn backend.api.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.api.assistant_provider import answer_assistant
from backend.api.provisional_decision import decide as provisional_decide
from backend.risk import simulate
from backend.risk.analytics import analyze
from backend.risk.analytics.sensitivity import grid
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
DEFAULT_SET = os.getenv("FIXTURE_SET", "demo_ethena_01")

app = FastAPI(title="DeFi Contagion API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# simulation_id -> scenario request, so /decide can follow up a /simulate call
_simulations: dict[str, dict] = {}


@lru_cache(maxsize=None)
def _set_files(name: str) -> dict[str, Any]:
    folder = CONTRACTS / "fixtures" / name
    if not (folder / "manifest.json").is_file():
        raise HTTPException(404, f"unknown fixture set {name!r}")
    manifest = json.loads((folder / "manifest.json").read_text())
    return {key: json.loads((folder / f["path"]).read_text()) for key, f in manifest["files"].items()}


def _files(name: str | None) -> dict[str, Any]:
    return _set_files(name or DEFAULT_SET)


@lru_cache(maxsize=None)
def _validator(schema_file: str) -> Draft202012Validator:
    registry = Registry()
    for path in (CONTRACTS / "schemas" / "v1").rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(json.loads((CONTRACTS / "schemas" / "v1" / schema_file).read_text()), registry=registry)


def _valid_request(request: dict) -> dict:
    errors = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in _validator("scenario_request.schema.json").iter_errors(request)]
    if errors:
        raise HTTPException(422, {"message": "scenario request does not match schema v1", "errors": errors[:10]})
    return request


def _run(fn, *args):
    try:
        return fn(*args)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc).strip("'\"")) from exc
    except ArithmeticError as exc:  # e.g. a scenario driving a value to zero: report it, never a 500
        raise HTTPException(422, f"scenario cannot be computed for these inputs ({type(exc).__name__}: {exc})") from exc


@app.get("/api/v1/health")
def health(set: str | None = Query(None)) -> dict:
    name = set or DEFAULT_SET
    _files(name)
    sets = sorted(p.name for p in (CONTRACTS / "fixtures").iterdir() if (p / "manifest.json").is_file())
    return {
        "status": "ok",
        "mode": "api",
        "schema_version": "1.0",
        "fixture_set": name,
        "fixture_sets": sets,
        "modules": {"discovery": "fixture", "risk": "live", "execution": "provisional (risk engine)", "assistant": "local Ollama + fallback"},
    }


@app.get("/api/v1/portfolio")
def portfolio(set: str | None = Query(None)) -> dict:
    return _files(set)["portfolio"]


@app.post("/api/v1/discover")
def discover(body: dict = Body(default={}), set: str | None = Query(None)) -> dict:
    files = _files(set)
    wanted = body.get("portfolio_id")
    if wanted and wanted != files["portfolio"]["portfolio_id"]:
        raise HTTPException(404, f"unknown portfolio_id {wanted!r}")
    return files["dependency_graph"]


@app.get("/api/v1/market-snapshot")
def market_snapshot(set: str | None = Query(None)) -> dict:
    return _files(set)["market_snapshot"]


@app.post("/api/v1/simulate")
def post_simulate(request: dict = Body(...), set: str | None = Query(None)) -> dict:
    files = _files(set)
    result = _run(simulate, files["portfolio"], files["market_snapshot"], _valid_request(request), files["dependency_graph"])
    _simulations[result["simulation_id"]] = request
    return result


@app.post("/api/v1/analyze")
def post_analyze(request: dict = Body(...), set: str | None = Query(None)) -> dict:
    files = _files(set)
    return _run(analyze, files["portfolio"], files["market_snapshot"], _valid_request(request))


@app.post("/api/v1/grid")
def post_grid(body: dict = Body(...), set: str | None = Query(None)) -> dict:
    """Loss / liquidation heatmap over any two scenario parameters."""
    files = _files(set)
    request = _valid_request(body.get("request", {}))
    try:
        xs, ys = [float(v) for v in body["x_values"]], [float(v) for v in body["y_values"]]
        x_param, y_param = body["x_param"], body["y_param"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "body needs request, x_param, x_values, y_param, y_values") from exc
    if len(xs) * len(ys) > 2500:
        raise HTTPException(422, "grid too large (max 2500 points)")
    p, s, r = (Portfolio.from_contract(files["portfolio"]), Snapshot.from_contract(files["market_snapshot"]),
               ScenarioRequest.from_contract(request))
    return _run(grid, p, s, r, x_param, xs, y_param, ys)


@app.post("/api/v1/decide")
def post_decide(body: dict = Body(...), set: str | None = Query(None)) -> dict:
    """Body: {position_id, and either request (scenario request) or simulation_id from /simulate}."""
    files = _files(set)
    request = body.get("request") or _simulations.get(body.get("simulation_id", "")) or files["scenario_request"]
    position_id = body.get("position_id") or files["portfolio"]["positions"][0]["position_id"]
    return _run(provisional_decide, files["portfolio"], files["market_snapshot"], _valid_request(request), position_id)


@app.post("/api/v1/assistant")
def assistant(body: dict = Body(...), set: str | None = Query(None)) -> dict:
    name = set or DEFAULT_SET
    return answer_assistant(body, _files(name), name)
