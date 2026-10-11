"""Backtest on recorded history (backend/risk/backtest/data): the engine's building blocks against reality."""

import pytest

from backend.risk.backtest import run as bt


@pytest.fixture(scope="module")
def history():
    return bt.load()


def test_pt_formula_matches_observed_pt_prices(history):
    # PT = USDe / (1 + implied APY)^(days / 365), fed with Pendle's implied APY, vs DefiLlama's PT price.
    r = bt.pt_pricing(history)
    assert r["observations"] > 10_000
    assert r["median_abs_bps"] < 2
    assert r["p95_abs_bps"] < 50


def test_susde_follows_usde_down_in_stress(history):
    # Engine default susde_market_beta = 1: on the days USDe fell >= 0.5%, sUSDe fell about as much (median ~0.9x).
    r = bt.susde_beta(history)
    assert r["stress_down_events"] >= 10
    assert 0.8 <= r["stress_down_median_ratio"] <= 1.05


def test_oct_10_2025_cex_crash_did_not_reach_the_morpho_oracle(history):
    c = bt.crash_replay(history)
    assert c["binance_low"] == pytest.approx(0.65)
    assert c["chainlink_low"] > 0.99  # the feed Morpho reads barely moved
    # Fed the CEX print with the oracle following the market, the engine liquidates Morpho; with the response the
    # feed actually had, nothing is liquidatable, which is what the oracle says happened.
    assert "morpho_01" in c["engine_binance_shock"]["liquidatable"]
    assert c["engine_binance_shock_observed_oracle"]["liquidatable"] == []
    assert c["engine_onchain_shock"]["liquidatable"] == []


def test_presets_are_far_beyond_recorded_oracle_moves(history):
    w = bt.worst_moves(history)
    assert w["usde_chainlink_min"]["price"] > 0.95  # worst oracle print: Bybit hack, Feb 21, 2025 (0.977)
    assert w["usde_onchain_24h"]["move"] > -0.05  # so the -5% preset is already a never-seen stress


def test_daily_replay_tracks_realised_pnl(history):
    r = bt.portfolio_replay(history)
    assert r["days"] >= 100
    assert r["correlation"] > 0.4
    assert r["mae_usd"] < 0.001 * r["nav"]  # under 10 bp of NAV a day
