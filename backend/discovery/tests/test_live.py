"""Hits Ethereum RPC and protocol APIs: run with DISCOVERY_LIVE=1 (optionally ETH_RPC_URL=...)."""

import os

import pytest

from backend.discovery.service import discover
from backend.discovery.tests.conftest import EXAMPLES, load

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("DISCOVERY_LIVE") != "1", reason="set DISCOVERY_LIVE=1 for network tests"),
]


def test_live_pt_holding_discovers_all_layers_now():
    graph, snapshot = discover(load(EXAMPLES / "pendle_pt_holding.json"), "live")  # validated inside
    layers = graph["coverage"]["pt_holding_01"]["layers"]
    assert layers["settlement_chain"]["status"] == "verified"
    assert layers["market_and_liquidity"]["status"] in ("verified", "inferred")
    assert snapshot["markets"]["pt_holding_01"]["market_kind"] == "pendle_pt_market"
    assert graph["discovery"]["rpc_calls"] > 0
