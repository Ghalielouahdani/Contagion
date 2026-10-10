import copy
from decimal import Decimal as D

import pytest

from backend.execution.decision import decide_position, load_contracts
from backend.execution.exit_cost import ExitCostEstimator

VENUE = {"quote_method": "proxy", "effective_depth_usd": "300000000", "fee_rate": "0.001", "gas_usd": "40"}


@pytest.fixture
def contracts():
    return load_contracts()


def run(c, estimator=None, position_id="aave_01"):
    kwargs = {"estimator": estimator} if estimator else {}
    return decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], position_id, **kwargs)


def test_priority_executable_then_pool_then_proxy():
    flat = lambda venue_id, venue, size: D("100")
    assert ExitCostEstimator(executable=flat, pool_reserves=flat).quote("v", VENUE, D(1000)).quote_status == "executable"
    assert ExitCostEstimator(pool_reserves=flat).quote("v", VENUE, D(1000)).quote_status == "pool_reserves"
    q = ExitCostEstimator().quote("v", VENUE, D(750000))
    assert (q.quote_status, round(q.price_impact_usd, 2), q.total_usd.quantize(D("0.01"))) == ("proxy", D("1870.32"), D("2660.32"))


def test_source_without_price_for_a_size_falls_back_per_size(contracts):
    small_only = lambda venue_id, venue, size: D("0") if size <= 1000000 else None   # devis jusqu'à 1 M$ seulement
    statuses = [o["quote_status"] for o in run(contracts, ExitCostEstimator(executable=small_only))["exit_options"]]
    assert statuses == ["executable", "executable", "proxy", "proxy", "proxy"]


def test_plugged_executable_quote_removes_proxy_flags(contracts):
    c = copy.deepcopy(contracts)
    c["scenario_request"]["assumptions"]["probability"] = "0.10"
    out = run(c, ExitCostEstimator(executable=lambda venue_id, venue, size: size * D("0.0005")))
    assert {o["quote_status"] for o in out["exit_options"]} == {"executable"}
    assert out["mode"] == "expected_cost"
    assert not any("proxy" in w for w in out["warnings"])


def test_no_price_at_all_gives_insufficient_data(contracts):
    c = copy.deepcopy(contracts)
    c["snapshot"]["exit_venues"]["venue:usde_usdc"]["effective_depth_usd"] = None
    c["scenario_request"]["assumptions"]["probability"] = "0.40"         # même avec une probabilité
    out = run(c)
    assert out["recommendation"] == "INSUFFICIENT_DATA" and out["mode"] == "conditional_stress"
    assert [(o["exit_fraction"], o["quote_status"]) for o in out["exit_options"]] == [("0.00", "unavailable")]
    assert out["exit_options"][0]["objective_usd"] is None


def test_missing_venue_gives_insufficient_data(contracts):
    c = copy.deepcopy(contracts)
    del c["snapshot"]["exit_venues"]["venue:usde_usdc"]
    assert run(c)["recommendation"] == "INSUFFICIENT_DATA"


def test_venue_claiming_better_method_than_used_is_flagged(contracts):
    c = copy.deepcopy(contracts)
    c["snapshot"]["exit_venues"]["venue:usde_usdc"]["quote_method"] = "executable_quote"
    out = run(c)
    assert {o["quote_status"] for o in out["exit_options"]} == {"proxy"}
    assert any("declares quote_method=executable_quote" in w for w in out["warnings"])
