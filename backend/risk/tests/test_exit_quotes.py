"""Exit costs from executable quotes (snapshot exit_venues.*.quotes) instead of one proxy depth."""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.risk.analytics import analyze
from backend.risk.liquidity import coverage, curve_loss_fraction, exit_cost, haircut
from backend.risk.model import Snapshot, Venue

LIVE = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "live_ethena_01"
CURVE = ((2e6, 0.001), (3e6, 0.002), (5e6, 0.10))  # cliff between 3m and 5m


def live(name: str) -> dict:
    return json.loads((LIVE / f"{name}.json").read_text())


def venue(curve=CURVE, depth=1e8) -> Venue:
    return Venue("venue:x", "sUSDe", depth, "executable_quote", curve=curve)


def test_curve_reproduces_quotes_and_interpolates():
    assert curve_loss_fraction(CURVE, 2e6) == pytest.approx(0.001)
    assert curve_loss_fraction(CURVE, 5e6) == pytest.approx(0.10)
    assert curve_loss_fraction(CURVE, 1e6) == pytest.approx(0.0005)  # from the (0, 0) anchor
    assert curve_loss_fraction(CURVE, 4e6) == pytest.approx(0.051)  # halfway up the cliff


def test_curve_extrapolation_is_constant_product_through_last_quote():
    depth = 5e6 * (1 / 0.10 - 1)  # 45m
    assert curve_loss_fraction(CURVE, 5e6 + 1e-6) == pytest.approx(0.10)  # continuous at the last quote
    assert curve_loss_fraction(CURVE, 1e7) == pytest.approx(1e7 / (depth + 1e7))


def test_curve_never_cheaper_for_a_bigger_trade():
    noisy = ((1e6, 0.004), (2e6, 0.002), (3e6, 0.006))  # second quote better than the first
    fractions = [curve_loss_fraction(noisy, s) for s in (5e5, 1e6, 1.5e6, 2e6, 2.5e6, 3e6)]
    assert fractions == sorted(fractions)


def test_proxy_venue_unchanged():
    proxy = venue(curve=(), depth=2e8)
    assert exit_cost(proxy, 2e6, 0.2) == haircut(2e6, 2e8 * 0.2)


def test_crisis_scales_the_book_uniformly():
    v = venue()
    for size in (1e6, 2.5e6, 4e6):
        assert exit_cost(v, size, 0.5) == pytest.approx(0.5 * exit_cost(v, size / 0.5))


def test_coverage_labels():
    v = venue()
    assert coverage(v, 4e6) == "quoted"
    assert coverage(v, 4e6, 0.5) == "extrapolated"  # like 8m in today's book
    assert coverage(venue(curve=()), 4e6) == "proxy"


def test_live_susde_exit_uses_the_quote_not_the_joint_depth():
    # Joint 5.0m sUSDe quote loses 12.89% (cliff): its constant-product depth (33.8m) prices a 2.0m exit
    # at 5.6%, but the 2.0m executable quote says 0.0913%.
    snapshot = Snapshot.from_contract(live("market_snapshot"))
    susde = snapshot.venues["venue:susde_usdc"]
    size = 2002952.69
    assert exit_cost(susde, size) == pytest.approx(size * 0.000913)
    assert haircut(size, susde.effective_depth_usd) > 50 * exit_cost(susde, size)


def test_live_derisking_savings_come_from_real_costs():
    # With one proxy depth, uniform de-risking looked 170k more expensive than targeted; real quotes say ~3.8k.
    portfolio, snapshot, request = live("portfolio"), live("market_snapshot"), live("scenario_request")
    proxy = copy.deepcopy(snapshot)
    for v in proxy["exit_venues"].values():
        v.pop("quotes", None)
    quoted = Decimal(analyze(portfolio, snapshot, request)["headline"]["derisking_savings_usd"])
    proxied = Decimal(analyze(portfolio, proxy, request)["headline"]["derisking_savings_usd"])
    assert quoted == Decimal("3710.41")  # 3,767.25 before sUSDe collateral yield counted in foregone carry
    assert proxied > 40 * quoted
