"""sUSDe posted as collateral keeps earning its own yield (exchange-rate accrual) even when the lending
protocol pays nothing on collateral: exiting such a position gives that yield up."""

import json
from decimal import Decimal as D
from pathlib import Path

from backend.execution.integration import decide
from backend.risk.model import Portfolio, Snapshot
from backend.risk.pricing import collateral_yield_apy

SET = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "stress_portfolio_01"


def load(name):
    return json.loads((SET / f"{name}.json").read_text())


def test_collateral_yield_adds_the_assets_own_yield():
    snapshot = Snapshot.from_contract(load("market_snapshot"))
    morpho = next(p for p in Portfolio.from_contract(load("portfolio")).positions if p.position_id == "morpho_01")
    assert snapshot.yields["morpho_01"]["collateral_supply_apy"] == 0.0  # Morpho pays nothing on collateral
    assert collateral_yield_apy(morpho, snapshot) == snapshot.asset_yields["sUSDe"] > 0


def test_exiting_a_susde_backed_borrow_gives_up_its_carry():
    # Before the fix the carry was -18.4k/yr (borrow cost only), so exiting looked free and every break-even was 0%.
    decision = decide(load("portfolio"), load("market_snapshot"), load("scenario_request"), "morpho_01", load("risk_result"))
    full = next(o for o in decision["exit_options"] if o["exit_fraction"] == "1.00")
    assert D(full["foregone_yield_usd"]) > 0
    assert D("0.008") < D(full["break_even_probability"]) < D("0.012")  # ~1%: cheap insurance at LTV 0.88
