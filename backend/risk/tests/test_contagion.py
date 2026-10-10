"""Contagion paths: losses explained through the dependency graph, cross-checked both ways."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk import simulate
from backend.risk.graph import Graph
from backend.risk.tests.conftest import by_id, with_params

SCHEMAS = Path(__file__).resolve().parents[3] / "contracts" / "schemas" / "v1"
ALL_FACTORS = dict(backing_impairment_pct="-0.02", susde_rate_cut_pct="-0.01")


def without_edge(graph, source, target):
    g = copy.deepcopy(graph)
    g["edges"] = [e for e in g["edges"] if not (e["source"] == source and e["target"] == target)]
    return g


def factors(position):
    return {p["factor"] for p in position["contagion"]["paths"]}


def test_every_loss_has_a_path_and_graph_agrees_with_valuation(portfolio, snapshot, graph, depeg_request):
    result = simulate(portfolio, snapshot, with_params(depeg_request, **ALL_FACTORS), graph)
    for position in result["positions"]:
        assert position["contagion"]["paths"], position["position_id"]
        assert position["contagion"]["graph_gaps"] == []
        assert position["contagion"]["unmodeled_exposures"] == []


def test_paths_follow_the_real_dependency_chains(portfolio, snapshot, graph, depeg_request):
    result = by_id(simulate(portfolio, snapshot, with_params(depeg_request, **ALL_FACTORS), graph))
    pendle = [p["nodes"] for p in result["pendle_01"]["contagion"]["paths"] if p["factor"] == "usde_price"]
    assert ["position:pendle_01", "asset:PT-sUSDe", "asset:sUSDe", "asset:USDe"] in pendle
    aave = [p["nodes"] for p in result["aave_01"]["contagion"]["paths"] if p["factor"] == "usde_price"]
    assert ["position:aave_01", "market:aave_01", "oracle:aave_01_usde", "asset:USDe"] in aave  # oracle channel
    assert "susde_exchange_rate" not in factors(result["aave_01"])  # USDe collateral: no sUSDe dependency
    assert "pt_implied_yield" not in factors(result["morpho_01"])


def test_missing_edge_is_flagged_never_a_silent_zero(portfolio, snapshot, graph, depeg_request):
    broken = without_edge(graph, "asset:sUSDe", "asset:USDe")
    full = by_id(simulate(portfolio, snapshot, depeg_request, graph))
    gap = by_id(simulate(portfolio, snapshot, depeg_request, broken))
    holding = gap["ethena_susde_01"]
    assert holding["conditional_loss_usd"] == full["ethena_susde_01"]["conditional_loss_usd"]  # amount unchanged
    assert any("asset:USDe" in g for g in holding["contagion"]["graph_gaps"])
    assert any("graph_gaps" in w for w in holding["warnings"])


def test_graph_dependency_without_modeled_loss_is_flagged(portfolio, snapshot, graph, depeg_request):
    g = copy.deepcopy(graph)
    g["edges"].append({**g["edges"][0], "id": "edge:extra", "source": "market:aave_01", "target": "asset:sUSDe",
                       "relation": "collateral_asset", "risk_channel": "mark_to_market"})
    aave = by_id(simulate(portfolio, snapshot, with_params(depeg_request, **ALL_FACTORS), g))["aave_01"]
    assert any("susde_exchange_rate" in u for u in aave["contagion"]["unmodeled_exposures"])


def test_confidence_is_the_weakest_edge_on_the_best_path(portfolio, snapshot, graph, depeg_request):
    verified = copy.deepcopy(graph)
    for edge in verified["edges"]:
        edge["confidence"], edge["evidence"]["status"] = "verified", "verified"
    result = by_id(simulate(portfolio, snapshot, depeg_request, verified))
    assert result["pendle_01"]["contagion"]["evidence_confidence"] == "verified"
    assert result["pendle_01"]["contagion"]["paths"][0]["unverified_edges"] == []
    assumed = by_id(simulate(portfolio, snapshot, depeg_request, graph))
    assert assumed["pendle_01"]["contagion"]["evidence_confidence"] == "assumed"


def test_hubs_show_one_failure_hitting_several_positions(portfolio, snapshot, graph, depeg_request):
    hubs = {h["node"]: h for h in simulate(portfolio, snapshot, depeg_request, graph)["contagion"]["hubs"]}
    assert len(hubs["asset:USDe"]["positions"]) == 4
    assert hubs["asset:USDe"]["net_equity_usd"] == "6200055.14"  # the whole NAV hangs on one asset
    assert hubs["venue:susde_usdc"]["positions"] == ["ethena_susde_01", "morpho_01"]
    assert "venue:usde_usdc" not in hubs  # only Aave exits there


def test_liquidity_paths_and_exit_mismatch(portfolio, snapshot, graph, liquidity_request):
    result = by_id(simulate(portfolio, snapshot, liquidity_request, graph))
    assert result["morpho_01"]["contagion"]["paths"][0]["nodes"] == ["position:morpho_01", "venue:susde_usdc"]
    broken = without_edge(graph, "position:morpho_01", "venue:susde_usdc")
    morpho = by_id(simulate(portfolio, snapshot, liquidity_request, broken))["morpho_01"]
    assert any("exits_via" in g for g in morpho["contagion"]["graph_gaps"])


def test_without_graph_numbers_are_unchanged_and_absence_is_explicit(portfolio, snapshot, graph, depeg_request):
    with_graph = simulate(portfolio, snapshot, depeg_request, graph)
    without = simulate(portfolio, snapshot, depeg_request)
    assert without["portfolio"] == with_graph["portfolio"]
    assert without["contagion"]["graph_id"] is None and without["contagion"]["warnings"]


def test_paths_are_shortest_first_and_simple():
    g = Graph.from_contract(json.loads((SCHEMAS.parents[1] / "fixtures" / "demo_ethena_01" / "dependency_graph.json").read_text()))
    paths = g.paths("position:morpho_01", "asset:USDe")
    assert [len(p) for p in paths] == sorted(len(p) for p in paths)
    for path in paths:
        nodes = [path[0].source] + [e.target for e in path]
        assert len(nodes) == len(set(nodes))


@pytest.mark.parametrize("request_name", ["depeg_request", "liquidity_request"])
def test_contagion_output_validates_against_schema(portfolio, snapshot, graph, request_name, request):
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((SCHEMAS / "risk_result.schema.json").read_text()), registry=registry)
    result = simulate(portfolio, snapshot, request.getfixturevalue(request_name), graph)
    errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(result)]
    assert not errors, errors
