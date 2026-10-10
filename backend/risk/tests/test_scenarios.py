"""Scenarios C-F: combined crisis, carry squeeze, governance change, node shock.

Reference values are derived by hand from the demo fixtures (see comments)."""

import copy
from decimal import Decimal

import pytest

from backend.risk import simulate
from backend.risk.tests.conftest import by_id, load, with_params

NEW = ["combined", "carry", "governance", "node_shock"]


def run(name: str, graph=None, horizon=None, **params) -> dict:
    request = with_params(load(f"scenario_request_{name}"), **params)
    if horizon is not None:
        request["scenario"]["horizon_days"] = horizon
    return simulate(load("portfolio"), load("market_snapshot"), request, graph)


def total(result: dict) -> Decimal:
    return Decimal(result["portfolio"]["total_conditional_loss_usd"])


def excess(result: dict) -> Decimal:
    return Decimal(result["comparison"]["excess_loss_usd"])


@pytest.mark.parametrize("name", NEW)
def test_results_reconcile_to_the_cent(name):
    result = run(name)
    positions = Decimal(0)
    for p in result["positions"]:
        loss = Decimal(p["conditional_loss_usd"])
        assert sum(Decimal(v) for v in p["loss_components"].values()) == loss
        assert Decimal(p["net_equity_before_usd"]) - loss == Decimal(p["net_equity_after_usd"])
        positions += loss
    assert positions + Decimal(result["portfolio"]["shared_liquidity_penalty_usd"]) == total(result)
    if "comparison" in result:
        runs = sum(Decimal(r["total_conditional_loss_usd"]) for r in result["comparison"]["runs"])
        assert total(result) - runs == excess(result)


@pytest.mark.parametrize("name", NEW)
def test_fixtures_have_no_graph_gaps(name):
    result = run(name, graph=load("dependency_graph"))
    for p in result["positions"]:
        assert p["contagion"]["graph_gaps"] == [], (p["position_id"], p["contagion"]["graph_gaps"])


# --- C. combined crisis -------------------------------------------------------------------------

def test_combined_without_depeg_is_the_liquidity_crisis():
    result = run("combined", usde_spot_shock_pct=0, pt_implied_apy_shock=0)
    assert total(result) == Decimal("920646.49")  # golden liquidity crisis, -80% depth


def test_combined_liquidation_selling_is_the_contagion():
    # -30%: Aave liquidated, liquidators sell 0.5 x 1.8M x 1.05 = 945k USDe into venue:usde_usdc (60M crisis depth).
    # Fund sells the remaining 2.1M - 0.945M = 1.155M behind it:
    # haircut(2.1M) - haircut(0.945M) = 56,361.53 instead of haircut(1.155M) = 21,813.83.
    result = run("combined")
    assert Decimal(by_id(result)["aave_01"]["loss_components"]["execution_haircut"]) == Decimal("56361.53")
    assert excess(result) == Decimal("34547.70")


def test_combined_no_liquidation_no_contagion():
    assert excess(run("combined", usde_spot_shock_pct=-0.05)) == 0


# --- D. carry squeeze ---------------------------------------------------------------------------

def test_carry_hand_values():
    result = by_id(run("carry"))
    # Morpho: no supply APY, sUSDe APY 0, debt 2M x 60% x 30/365.
    assert Decimal(result["morpho_01"]["loss_components"]["negative_carry"]) == Decimal("98630.14")
    # Aave: debt 1.8M x 60% x 30/365 = 88,767.12 minus collateral 3M x 5% x 30/365 = 12,328.77.
    assert Decimal(result["aave_01"]["conditional_loss_usd"]) == Decimal("76438.36")
    assert Decimal(result["ethena_susde_01"]["conditional_loss_usd"]) == 0
    assert Decimal(result["pendle_01"]["conditional_loss_usd"]) < 0  # PT pulls to par: a gain


def test_carry_days_to_liquidation():
    # Aave: 3M(1 + 0.05t) x 0.85 = 1.8M(1 + 0.6t) -> t = 287.4 days; Morpho: 2M(1 + 0.6t) / 3M = 0.915 -> 226.6 days.
    result = by_id(run("carry"))
    assert any("after about 288 days" in w for w in result["aave_01"]["warnings"])
    assert any("after about 227 days" in w for w in result["morpho_01"]["warnings"])


def test_carry_at_current_rates_has_no_excess():
    result = run("carry", susde_apy=0.07, borrow_apy_override=None)
    assert excess(result) == 0
    assert total(result) < 0  # positive carry is a gain


def test_carry_monotonic_in_borrow_rate():
    losses = [total(run("carry", borrow_apy_override=r)) for r in (0.05, 0.2, 0.6, 1.0)]
    assert losses == sorted(losses)


@pytest.mark.parametrize("apy", [-0.10, -0.50, -1.0])
@pytest.mark.parametrize("horizon", [1, 30, 365, 3650])
def test_carry_deeply_negative_sUSDe_apy_does_not_crash(apy, horizon):
    # Regression: the days-to-liquidation search projected sUSDe collateral to 0 -> division by zero in LTV.
    result = run("carry", horizon=horizon, susde_apy=apy)
    assert by_id(result)["morpho_01"]["conditional_loss_usd"]


def test_carry_negative_sUSDe_apy_shortens_time_to_liquidation():
    result = by_id(run("carry", susde_apy=-0.10))
    days = int(next(w for w in result["morpho_01"]["warnings"] if "after about" in w).split("about ")[1].split()[0])
    assert days < 227  # faster than with a 0% sUSDe APY


def test_carry_long_squeeze_liquidates():
    result = by_id(run("carry", horizon=300))
    assert result["aave_01"]["risk_metric"]["liquidatable"] is True
    assert result["morpho_01"]["risk_metric"]["liquidatable"] is True


# --- E. governance change -----------------------------------------------------------------------

def test_governance_without_change_is_the_depeg():
    result = run("governance", liquidation_threshold_shift=0, oracle_switch_pass_through=None)
    assert excess(result) == 0


def test_governance_change_creates_liquidations():
    # -27%: survivable today (Aave HF 1.034, Morpho oracle ignores the depeg). After LT -5 pts and the
    # Morpho oracle switch: Aave HF 0.973 (50% x 1.8M x 5% = 45k), Morpho LTV 0.913 > 0.865 (2M x 2.6% = 52k).
    result = run("governance")
    positions = by_id(result)
    assert positions["aave_01"]["risk_metric"]["liquidatable"] is True
    assert positions["morpho_01"]["risk_metric"]["liquidatable"] is True
    assert excess(result) == Decimal("97000.00")


def test_governance_targets_one_market():
    result = by_id(run("governance", target_markets=None, oracle_switch_pass_through=None))
    assert result["morpho_01"]["risk_metric"]["liquidatable"] is False
    request = load("scenario_request_governance")
    request["scenario"]["parameters"]["target_markets"] = ["aave_01"]
    only_aave = by_id(simulate(load("portfolio"), load("market_snapshot"), request))
    assert only_aave["aave_01"]["risk_metric"]["threshold"] == "1.0000"
    assert only_aave["morpho_01"]["risk_metric"]["threshold"] == "0.9150"  # untouched


# --- F. node shock ------------------------------------------------------------------------------

def node(node_id: str, loss: float, graph=None) -> dict:
    return run("node_shock", graph=graph, node_id=node_id, loss_pct=loss)


def test_backing_failure_does_not_move_the_morpho_oracle():
    result = by_id(node("offchain:ethena_backing", 0.10))
    assert result["morpho_01"]["risk_metric"]["after"] == result["morpho_01"]["risk_metric"]["before"]
    assert Decimal(result["morpho_01"]["conditional_loss_usd"]) == Decimal("300000.00")  # mark loss still real


def test_susde_node_spares_aave():
    result = by_id(node("asset:sUSDe", 0.10))
    assert Decimal(result["aave_01"]["conditional_loss_usd"]) == 0
    assert Decimal(result["morpho_01"]["risk_metric"]["after"]) > Decimal(result["morpho_01"]["risk_metric"]["before"])


def test_usdc_depeg_is_a_gain_for_borrowers():
    result = node("asset:USDC", 0.10)
    assert total(result) == Decimal("-380000.00")  # 3.8M of USDC debt x 10%


def test_protocol_failure_capped_at_net_equity():
    result = by_id(node("protocol:morpho", 0.50))  # 1.5M of collateral lost, net equity 1.0M
    assert Decimal(result["morpho_01"]["conditional_loss_usd"]) == Decimal("1000000.00")
    assert Decimal(result["morpho_01"]["net_equity_after_usd"]) == 0
    assert all(Decimal(result[p]["conditional_loss_usd"]) == 0 for p in ("aave_01", "pendle_01", "ethena_susde_01"))


def test_pendle_failure_follows_the_graph():
    result = node("protocol:pendle", 0.10, graph=load("dependency_graph"))
    hit = [p["position_id"] for p in result["positions"] if Decimal(p["conditional_loss_usd"]) != 0]
    assert hit == ["pendle_01"]
    assert by_id(result)["pendle_01"]["contagion"]["paths"]


@pytest.mark.parametrize("node_id", ["venue:susde_usdc", "oracle:aave_01_usde"])
def test_unpriced_nodes_are_rejected(node_id):
    with pytest.raises(ValueError):
        node(node_id, 0.10)


def test_node_missing_from_graph_is_flagged():
    graph = copy.deepcopy(load("dependency_graph"))
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "protocol:pendle"]
    graph["edges"] = [e for e in graph["edges"] if "protocol:pendle" not in (e["source"], e["target"])]
    result = node("protocol:pendle", 0.10, graph=graph)
    assert any("not in the dependency graph" in w for w in result["contagion"]["warnings"])
    assert by_id(result)["pendle_01"]["contagion"]["graph_gaps"]


@pytest.mark.parametrize("name", NEW)
def test_request_fixtures_validate_against_schema(name):
    import json

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from backend.risk.tests.test_golden import SCHEMAS

    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((SCHEMAS / "scenario_request.schema.json").read_text()), registry=registry)
    errors = [e.message for e in validator.iter_errors(load(f"scenario_request_{name}"))]
    assert not errors, errors
