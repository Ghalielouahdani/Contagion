"""Real wallet import (backend/discovery/wallet.py), replayed offline from its recording."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.discovery import discover
from backend.discovery.wallet import CASSETTES, FIXTURES, import_wallet

ADDRESS = "0xCf0a12CBd8088fc5f84ad431E71787157041cD69"
SET = FIXTURES / "wallet_cf0a12"


def load(name):
    return json.loads((SET / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def wallet():
    return import_wallet(ADDRESS, "replay", CASSETTES / "wallet_cf0a12_wallet.json")


def test_positions_are_read_on_chain_and_out_of_scope_ones_are_listed(wallet):
    assert [p["position_id"] for p in wallet.positions] == [
        "morpho_susde_pyusd", "morpho_usde_rlusd", "aave_usde_usdc", "aave_usde_usdt"]
    assert all(p["data_origin"] == "observed" for p in wallet.positions)
    assert any("PT-sUSDS" in s for s in wallet.skipped)  # not dropped silently
    stored = {p["position_id"]: p for p in load("portfolio")["positions"]}
    for p in wallet.positions:  # the stored set holds exactly what was read, revalued in USD
        for key in ("collateral_quantity", "debt_quantity", "market_id"):
            assert p[key] == stored[p["position_id"]][key]


def test_aave_account_is_split_without_losing_collateral_or_debt(wallet):
    aave = [p for p in wallet.positions if p["protocol"] == "aave"]
    debt = {p["debt_asset"]: D(p["debt_quantity"]) for p in aave}
    collateral = sum(D(p["collateral_quantity"]) for p in aave)
    # each pair gets the collateral share of its debt: the split adds back to the account
    for p in aave:
        share = debt[p["debt_asset"]] / sum(debt.values())
        assert float(D(p["collateral_quantity"]) / collateral) == pytest.approx(float(share), rel=1e-6)


def test_discovery_of_the_wallet_replays_to_the_stored_set(wallet):
    ids = load("manifest")["ids"]
    graph, snapshot = discover(wallet.portfolio(ids["portfolio_id"]), "replay", cassette=CASSETTES / "wallet_cf0a12.json",
                               graph_id=ids["graph_id"], snapshot_id=ids["snapshot_id"])
    assert {k: v for k, v in snapshot.items() if k != "warnings"} == \
        {k: v for k, v in load("market_snapshot").items() if k != "warnings"}
    assert graph["nodes"] == load("dependency_graph")["nodes"] and graph["unresolved"] == []
    markets = snapshot["markets"]
    for pid in ("morpho_susde_pyusd", "morpho_usde_rlusd"):  # the cascade sees the real borrowers
        assert markets[pid]["borrower_ltv_buckets"] and markets[pid]["borrower_distribution_source_type"] == "observed"
    assert "RLUSD" in snapshot["prices_usd"]  # every position is valued


def test_crisis_plans_never_show_a_gain_from_holding_a_leveraged_position():
    for plan_file in SET.glob("crisis_plan*.json"):
        for row in json.loads(plan_file.read_text())["positions"]:
            assert D(row["holding_loss_usd"]) >= 0, (plan_file.name, row["position_id"])


def test_invalid_address_is_rejected():
    with pytest.raises(ValueError, match="not an Ethereum address"):
        import_wallet("0x123")
