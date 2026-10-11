"""Scenario A: USDe market depeg (blueprint section 7.1).

Three distinct mechanisms, never reused as one multiplier:
- usde_spot_shock_pct: market price move (seen by oracles according to their pass-through);
- backing_impairment_pct: USDe backing loss (repriced by the market; an exchange-rate
  oracle with USDe hardcoded at 1 USD does not see it);
- susde_rate_cut_pct: loss socialised to stakers (every sUSDe oracle reads the rate).
"""

from __future__ import annotations

from backend.risk import lending
from backend.risk import trace as T
from backend.risk.metrics import liquidate, read_metric
from backend.risk.model import Portfolio, Position, PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.pricing import MarketState, asset_price, oracle_price, position_values
from backend.risk.scenarios import scenario


@scenario("usde_depeg")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    shock = request.param("usde_spot_shock_pct", 0.0)
    beta = request.param("susde_market_beta", 1.0)
    impairment = request.param("backing_impairment_pct", 0.0)
    rate_cut = request.param("susde_rate_cut_pct", 0.0)
    apy_shift = request.param("pt_implied_apy_shock", 0.0)
    lag_hours = request.param("oracle_lag_hours", 0.0)

    before = MarketState.from_snapshot(snapshot)
    states = {
        "before": before,
        "market_only": before.shocked(shock, beta, 0.0, apy_shift),  # depeg alone
        "no_rate_cut": before.shocked(shock, beta, impairment, apy_shift),  # what market-price oracles see
        "after": before.shocked(shock, beta, impairment, apy_shift, susde_rate_cut=rate_cut),
    }

    outcome = ScenarioOutcome(impacts=[])
    for position in portfolio.positions:
        outcome.impacts.append(_impact(position, snapshot, states, rate_cut, request))
    if lag_hours and any(i.risk_metric and i.risk_metric["liquidatable"] for i in outcome.impacts):
        outcome.warnings.append(
            f"Oracle lag of {lag_hours:g}h: liquidatable positions can still be deleveraged before the oracle updates "
            "(see risk analytics: avoidable liquidation penalty)."
        )
    return outcome


def _impact(position: Position, snapshot: Snapshot, states: dict[str, MarketState], rate_cut: float,
            request: ScenarioRequest) -> PositionImpact:
    gross0, debt0 = position_values(position, states["before"], snapshot)
    gross_m, debt_m = position_values(position, states["market_only"], snapshot)
    gross1, debt1 = position_values(position, states["after"], snapshot)

    impact = PositionImpact(
        position_id=position.position_id,
        gross_before=gross0,
        gross_after=gross1,
        debt_after=debt1,
        net_before=gross0 - debt0,
        loss_components={
            "market_repricing": (gross0 - debt0) - (gross_m - debt_m),
            "backing_impairment": (gross_m - debt_m) - (gross1 - debt1),  # USDe impairment + sUSDe rate cut
            "liquidation_penalty": 0.0,
            "execution_haircut": 0.0,
        },
    )
    _trace_valuation(impact, position, snapshot, states, request, (gross0, debt0), (gross_m, debt_m), (gross1, debt1))
    if position.position_type == "pt_holding":
        impact.warnings.append("PT valued with implied-APY discount approximation.")
    if position.is_borrow:
        _apply_liquidation_metric(impact, position, snapshot, states, rate_cut, request)
    elif lending.is_lender(position):
        _apply_lender_loss(impact, position, snapshot, states, rate_cut, request)
    return impact


def _pass_through(market: dict, request: ScenarioRequest, impact: PositionImpact) -> float:
    override = request.param("oracle_pass_through_override")
    if override is not None:
        return override
    if "oracle_pass_through" in market:
        return float(market["oracle_pass_through"])
    impact.warnings.append("Oracle pass-through unknown; assumed 1.0 (oracle follows market).")
    return 1.0


def _apply_lender_loss(impact: PositionImpact, position: Position, snapshot: Snapshot,
                       states: dict[str, MarketState], rate_cut: float, request: ScenarioRequest) -> None:
    """Supplier of the loan asset: loses only what borrowers' collateral no longer covers (see lending.py)."""
    market = snapshot.market(position.position_id)
    asset = None if market is None else market.get("collateral_asset")
    if asset is None:
        impact.insufficient_data = True
        impact.warnings.append("No lending market or collateral asset: lender loss not computed.")
        return
    try:
        price0 = asset_price(asset, states["before"], market)
        move = asset_price(asset, states["no_rate_cut"], market) / price0 - 1
    except (KeyError, ValueError):
        impact.insufficient_data = True
        impact.warnings.append(f"No pricing rule for collateral {asset}: lender loss not computed.")
        return
    pass_through = _pass_through(market, request, impact)
    cut = rate_cut if asset == "sUSDe" else 0.0
    shocked = lending.shock(position, market, move, pass_through, cut)
    if shocked is None:
        impact.insufficient_data = True
        impact.warnings.append("No borrower distribution or market supply: lender loss not computed.")
        return

    bad, under = shocked.share * shocked.bad_debt, shocked.share * shocked.undercollateralized
    impact.loss_components["bad_debt"] = bad
    impact.loss_components["undercollateralized_debt"] = under
    impact.gross_after -= bad + under  # the claim on the market is worth what borrowers can still repay
    impact.internals = {"market": market, "lender": shocked}
    source = T.market_source(snapshot, position.position_id)
    T.step(impact.trace, "lender_loss", "Lender loss: what borrowers' collateral no longer covers",
           "share x (bad debt + underwater debt); bad debt = debt - oracle collateral / LIF when liquidated, "
           "underwater = debt - market collateral when the oracle does not see the move",
           [T.inp("our supply share", shocked.share, T.RATIO, source),
            T.inp(f"{asset} market move", move, T.PCT, T.DERIVED),
            T.inp("oracle pass-through", pass_through, T.RATIO, source),
            T.inp("LLTV", float(market["lltv"]), T.RATIO, source),
            T.inp("LIF = 1 + liquidation incentive", 1 + float(market.get("liquidation_incentive", 0)), T.RATIO, source),
            T.inp("market bad debt", shocked.bad_debt, T.USD, T.DERIVED),
            T.inp("market underwater debt", shocked.undercollateralized, T.USD, T.DERIVED)],
           bad + under, T.USD,
           note=f"Borrower distribution: {market.get('borrower_distribution_source_type', 'assumed')}.",
           rows=list(shocked.rows))
    impact.warnings.append(
        f"Lender share {shocked.share:.2%} of the market; {shocked.liquidatable_debt / shocked.total_debt:.0%} of borrower "
        f"debt becomes liquidatable ({asset} oracle pass-through {pass_through:g}).")
    if under > 0:
        realised = lending.shock(position, market, move, 1.0, cut)
        impact.warnings.append(
            f"{under:,.0f} USD of our share is underwater at market prices but invisible to the oracle: not yet realised "
            f"by the protocol. With an oracle that follows the market, realised bad debt would be "
            f"{realised.share * realised.bad_debt:,.0f} USD.")
    if market.get("borrower_distribution_source_type", "assumed") != "observed":
        impact.warnings.append("Borrower LTV distribution is an assumption, not indexed borrower positions.")


def _apply_liquidation_metric(impact: PositionImpact, position: Position, snapshot: Snapshot,
                              states: dict[str, MarketState], rate_cut: float, request: ScenarioRequest) -> None:
    market = snapshot.market(position.position_id)
    if market is None:
        impact.insufficient_data = True
        impact.warnings.append("No market parameters: liquidation risk not computed.")
        return

    pass_through = _pass_through(market, request, impact)

    asset = position.collateral_asset
    price0 = asset_price(asset, states["before"], market)
    move = asset_price(asset, states["no_rate_cut"], market) / price0 - 1
    cut = rate_cut if asset == "sUSDe" else 0.0
    debt0 = position.debt_quantity * asset_price(position.debt_asset, states["before"], market)

    def reading(pt: float):
        collateral_after = position.collateral_quantity * oracle_price(price0, move, pt, cut)
        return collateral_after, read_metric(market, position.collateral_quantity * price0, collateral_after, debt0, impact.debt_after)

    oracle_collateral, metric = reading(pass_through)
    impact.risk_metric = metric.as_contract()
    _trace_metric(impact, position, snapshot, market, price0, move, pass_through, cut, oracle_collateral, debt0, metric)
    impact.internals = {"market": market, "oracle_collateral_after": oracle_collateral, "metric": metric}
    settle_borrow(impact, market, oracle_collateral, metric, T.market_source(snapshot, position.position_id))
    if not market.get("verified"):
        impact.warnings.append("Liquidation parameters and oracle response are fixture assumptions.")
    if pass_through < 1:
        _, alt = reading(1.0)
        impact.warnings.append(
            f"Oracle assumed to pass through {pass_through:g} of the market move; if it fully follows the market, "
            f"{alt.type} becomes {alt.after:.4f} (liquidatable: {alt.liquidatable})."
        )


def settle_borrow(impact: PositionImpact, market: dict, oracle_collateral: float, metric, source: str) -> None:
    """Liquidation penalty (protocol rules, repeated until safe) and limited liability of a borrow position.

    The debt is non-recourse: once the collateral is worth less than the debt, the borrower walks
    away and loses its net equity, never more. That relief is its own (negative) component,
    `limited_liability`, so the published loss never exceeds the equity at stake.
    """
    if metric.liquidatable:
        liq = liquidate(market, impact.gross_after, oracle_collateral, impact.debt_after)
        impact.internals["liquidation"] = liq
        impact.loss_components["liquidation_penalty"] = liq.loss
        T.step(impact.trace, "liquidation_penalty", "Liquidation penalty",
               "repeat while liquidatable: repay close factor x debt, seize repaid x (1 + incentive) at the oracle "
               "price (capped at the collateral left); penalty = collateral seized at market value - debt repaid",
               [T.inp("close factor at the breach", metric.close_factor, T.RATIO, T.RULE),
                T.inp("debt after", impact.debt_after, T.USD, T.DERIVED),
                T.inp("liquidation incentive", metric.liquidation_incentive, T.RATIO, source),
                T.inp("liquidation calls", liq.steps, "count", T.DERIVED),
                T.inp("debt repaid", liq.repaid, T.USD, T.DERIVED),
                T.inp("collateral seized (market value)", liq.seized_market, T.USD, T.DERIVED),
                T.inp("debt written off (collateral exhausted)", liq.written_off, T.USD, T.DERIVED)],
               liq.loss, T.USD,
               note="Liquidators keep the incentive as a bonus taken from the collateral; a position whose collateral "
                    "runs out loses all of it and its remaining debt becomes the lenders' bad debt.")
        if liq.unprofitable:
            impact.warnings.append(
                "Liquidatable, but the collateral liquidators would seize at the oracle price is worth less at market "
                "than the debt they would repay: no rational liquidator acts, the position stays open.")
        else:
            impact.warnings.append(
                f"Liquidatable: {liq.steps} liquidation call(s) repay {liq.repaid:,.0f} USD of debt"
                + (f"; collateral exhausted, {liq.written_off:,.0f} USD of debt written off" if liq.written_off else "")
                + "; penalty = collateral seized at market value - debt repaid.")
    cap_loss(impact)


def cap_loss(impact: PositionImpact) -> None:
    """Limited liability of a borrow position: its loss never exceeds its net equity.

    Recomputed from the other components, so a scenario that adds a cost later (an exit haircut)
    calls it again. limited_liability = min(net equity after every other component, 0).
    """
    others = sum(v for k, v in impact.loss_components.items() if k != "limited_liability")
    net_after = impact.net_before - others
    had = "limited_liability" in impact.loss_components
    if net_after >= 0:
        if had:
            impact.loss_components["limited_liability"] = 0.0
        return
    impact.loss_components["limited_liability"] = net_after
    if had:
        return
    T.step(impact.trace, "limited_liability", "Limited liability: the debt is non-recourse",
           "min(net equity before - every other loss component, 0)",
           [T.inp("net equity before", impact.net_before, T.USD, T.DERIVED),
            T.inp("losses before the cap", others, T.USD, T.DERIVED)],
           net_after, T.USD, note="The borrower walks away: it loses its net equity, the shortfall is the lenders'.")
    impact.warnings.append(
        f"Losses exceed the position's net equity by {-net_after:,.0f} USD: the position is lost (loss capped at its "
        "net equity); the shortfall falls on the lenders.")


# Calculation trace ---------------------------------------------------------------------------
def _trace_price(impact: PositionImpact, asset: str, snapshot: Snapshot, states: dict[str, MarketState],
                 request: ScenarioRequest, market: dict | None) -> None:
    """Before/after market price of one asset, with the formula of each shock applied to it."""
    p = request.param
    before, after = asset_price(asset, states["before"], market), asset_price(asset, states["after"], market)
    shocks = [T.inp("USDe spot shock", p("usde_spot_shock_pct", 0.0), T.PCT, T.SCENARIO),
              T.inp("backing impairment", p("backing_impairment_pct", 0.0), T.PCT, T.SCENARIO)]
    if asset == "USDe":
        formula = "USDe price x (1 + spot shock) x (1 + backing impairment)"
        inputs = [T.inp("USDe price", before, T.PRICE, T.price_source(snapshot, "USDe"))] + shocks
    elif asset == "sUSDe":
        formula = "sUSDe price x (1 + beta x spot shock) x (1 + backing impairment) x (1 + sUSDe rate cut)"
        inputs = [T.inp("sUSDe price = sUSDe/USDe rate x USDe price", before, T.PRICE, T.snapshot_rate_source(snapshot)),
                  T.inp("sUSDe beta to USDe", p("susde_market_beta", 1.0), T.RATIO, T.SCENARIO)] + shocks + [
                  T.inp("sUSDe rate cut", p("susde_rate_cut_pct", 0.0), T.PCT, T.SCENARIO)]
    elif asset.startswith("PT-") and market is not None:
        days = float(market["days_to_maturity"])
        formula = "USDe price after x (1 + sUSDe rate cut) / (1 + implied APY + APY shock) ^ (days / 365)"
        inputs = [T.inp("implied APY", float(market["pt_implied_apy"]), T.PCT, T.market_source(snapshot, impact.position_id)),
                  T.inp("implied APY shock", p("pt_implied_apy_shock", 0.0), T.PCT, T.SCENARIO),
                  T.inp("days to maturity", days, T.DAYS, T.market_source(snapshot, impact.position_id)),
                  T.inp("price before", before, T.PRICE, T.DERIVED)]
    else:
        formula = "stablecoin price (not shocked by this scenario)"
        inputs = [T.inp(f"{asset} price", before, T.PRICE, T.price_source(snapshot, asset))]
    T.step(impact.trace, f"price:{asset}", f"{asset} market price after the shock", formula, inputs, after, T.PRICE)


def _trace_valuation(impact: PositionImpact, position: Position, snapshot: Snapshot, states: dict[str, MarketState],
                     request: ScenarioRequest, before: tuple, market_only: tuple, after: tuple) -> None:
    market = snapshot.market(position.position_id)
    assets = [position.collateral_asset, position.debt_asset] if position.is_borrow else [position.asset_symbol]
    for asset in assets:
        try:
            _trace_price(impact, asset, snapshot, states, request, market)
        except (KeyError, ValueError):
            continue
    if position.is_borrow:
        T.step(impact.trace, "value", "Collateral and debt after the shock",
               "net equity = collateral quantity x collateral price - debt quantity x debt price",
               [T.inp(f"{position.collateral_asset} collateral", position.collateral_quantity, T.TOKENS, "fictional"),
                T.inp("collateral value after", after[0], T.USD, T.DERIVED),
                T.inp(f"{position.debt_asset} debt", position.debt_quantity, T.TOKENS, "fictional"),
                T.inp("debt value after", after[1], T.USD, T.DERIVED),
                T.inp("net equity before", before[0] - before[1], T.USD, T.DERIVED)],
               after[0] - after[1], T.USD)
    else:
        T.step(impact.trace, "value", f"{position.asset_symbol} holding value after the shock",
               "quantity x price after",
               [T.inp("quantity", position.quantity, T.TOKENS, "fictional"),
                T.inp("value before", before[0], T.USD, T.DERIVED)],
               after[0], T.USD)
    T.step(impact.trace, "split", "Loss split by mechanism",
           "market repricing = net before - net after the depeg alone; backing impairment = the rest of the move",
           [T.inp("net before", before[0] - before[1], T.USD, T.DERIVED),
            T.inp("net after the depeg alone", market_only[0] - market_only[1], T.USD, T.DERIVED),
            T.inp("net after all shocks", after[0] - after[1], T.USD, T.DERIVED)],
           (before[0] - before[1]) - (after[0] - after[1]), T.USD,
           note="The depeg is applied alone first, so market repricing and backing loss are never counted twice.")


def _trace_metric(impact: PositionImpact, position: Position, snapshot: Snapshot, market: dict, price0: float,
                  move: float, pass_through: float, cut: float, oracle_collateral: float, debt0: float, metric) -> None:
    source = T.market_source(snapshot, position.position_id)
    T.step(impact.trace, "oracle", "Collateral value seen by the protocol's oracle",
           "collateral quantity x price before x (1 + pass-through x market move) x (1 + sUSDe rate cut)",
           [T.inp("collateral quantity", position.collateral_quantity, T.TOKENS, "fictional"),
            T.inp("price before", price0, T.PRICE, T.DERIVED),
            T.inp("market move of the collateral", move, T.PCT, T.DERIVED),
            T.inp(f"oracle pass-through ({market.get('oracle_type', 'unknown')})", pass_through, T.RATIO, source),
            T.inp("sUSDe rate cut", cut, T.PCT, T.SCENARIO)],
           oracle_collateral, T.USD,
           note="Pass-through 1 = the oracle reads the market price; 0 = it ignores the depeg (exchange-rate oracle).")
    if metric.type == "health_factor":
        formula, inputs = "HF = oracle collateral x liquidation threshold / debt; liquidatable when HF < 1", [
            T.inp("oracle collateral", oracle_collateral, T.USD, T.DERIVED),
            T.inp("liquidation threshold", float(market["liquidation_threshold"]), T.RATIO, source),
            T.inp("debt", impact.debt_after, T.USD, T.DERIVED)]
    else:
        formula, inputs = "LTV = debt / oracle collateral; liquidatable when LTV > LLTV", [
            T.inp("debt", impact.debt_after, T.USD, T.DERIVED),
            T.inp("oracle collateral", oracle_collateral, T.USD, T.DERIVED),
            T.inp("LLTV", metric.threshold, T.RATIO, source)]
    T.step(impact.trace, "metric", f"{metric.type.replace('_', ' ')} after the shock", formula, inputs, metric.after, T.RATIO,
           note=f"Before: {metric.before:.4f}. Liquidatable: {metric.liquidatable}. Distance to liquidation after: "
                f"{metric.distance_after:.2%} of further oracle price drop.")
