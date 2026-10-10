import pytest

from backend.adapters.oracles import Driver, OracleReport, usde_pass_through
from backend.discovery.query import explain, impacted_by


def report(*drivers, alternates=()):
    r = OracleReport("0x0", "oracle:x", "test", "test", list(drivers))
    r.alternates = list(alternates)
    return r


@pytest.mark.parametrize(
    "drivers, value, kind",
    [
        ([Driver("feed", "USDe/USD")], "1", "market_price_feed"),
        (
            [Driver("rate", "sUSDe"), Driver("feed", "USDe/USD"), Driver("feed", "PYUSD/USD", "quote")],
            "1",
            "exchange_rate_x_market_feed",
        ),
        ([Driver("rate", "sUSDe")], "0", "exchange_rate_usde_hardcoded"),
        ([Driver("rate", "sUSDe"), Driver("feed", "USDT/USD")], "0", "exchange_rate_x_proxy_feed"),
        ([Driver("feed", "USDT/USD")], "0", "proxy_asset_feed"),
        ([Driver("linear_discount", "PT-x")], "0", "pt_linear_discount_hardcoded_peg"),
    ],
)
def test_pass_through_follows_the_active_inputs(drivers, value, kind):
    result = usde_pass_through(report(*drivers))
    assert (result.value, result.oracle_type) == (value, kind)


def test_backup_oracle_is_reported_but_not_active():
    r = report(
        Driver("linear_discount", "PT-x"), alternates=[Driver("linear_discount", "PT-x"), Driver("feed", "USDe/USD")]
    )
    result = usde_pass_through(r)
    assert result.value == "0" and result.backup_value == "1" and result.oracle_type.endswith("_with_backup")


def test_unclassified_component_makes_pass_through_unknown():
    assert usde_pass_through(report(Driver("unknown", "0xabc"))).value is None


def test_usde_shock_reaches_every_position(replay):
    _, graph, _ = replay("live_ethena_01")
    rows = impacted_by(graph, "asset:USDe")
    assert {r["position_id"] for r in rows} == {"ethena_susde_01", "aave_01", "morpho_01", "pendle_01"}
    for r in rows:
        assert r["paths"][0]["nodes"][0] == f"position:{r['position_id']}"
        assert r["paths"][0]["nodes"][-1] == "asset:USDe"


def test_tether_reaches_only_the_aave_position(replay):
    _, graph, _ = replay("live_ethena_01")
    rows = impacted_by(graph, "offchain:tether")
    assert [r["position_id"] for r in rows] == ["aave_01"]
    assert "oracle_repricing" in rows[0]["paths"][0]["channels"]


def test_impacted_by_unknown_node_raises(replay):
    _, graph, _ = replay("live_ethena_01")
    with pytest.raises(KeyError):
        impacted_by(graph, "asset:does_not_exist")


def test_explain_shows_all_five_layers(replay):
    _, graph, _ = replay("pendle_pt_morpho_collateral")
    text = explain(graph, "pt_collateral_01")
    for layer in (
        "settlement_chain",
        "yield_source_and_issuer",
        "oracle",
        "market_and_liquidity",
        "lending_collateral_market",
    ):
        assert layer in text
    assert "Pendle linear-discount feed" in text
