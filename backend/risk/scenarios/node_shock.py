"""Scenario F: shock one dependency-graph node (exploit, custodian or exchange failure, stablecoin depeg).

The node decides the mechanism, so a node shock reuses the exact pricing and oracle rules:
- asset:USDe, protocol:ethena, offchain:* (Ethena backing, custodians): USDe backing loss
  (scenario A backing_impairment_pct). Exchange-rate oracles do not see it.
- asset:sUSDe: loss socialised to stakers (scenario A susde_rate_cut_pct). Every oracle sees it.
- asset:<stablecoin>: the stablecoin depegs. Borrowers owe less in USD: a gain for the debt side.
- protocol:<x>, market:<position_id>, asset:PT-*: protocol failure. Positions in that protocol,
  market or token lose loss_pct of their gross value; a borrower loses at most its net equity
  (it can walk away from the debt once the collateral is gone).

Who is hit comes from valuation; contagion.annotate cross-checks it against the graph paths
to the node, so a missing edge or an unmodeled exposure is flagged, never silent.
"""

from __future__ import annotations

from dataclasses import replace

from backend.risk.metrics import read_metric
from backend.risk.model import Portfolio, Position, PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.pricing import STABLES, MarketState, position_values
from backend.risk.scenarios import scenario, usde_depeg

ETHENA_NODES = ("asset:USDe", "protocol:ethena")
NEUTRAL_DEPEG = {"usde_spot_shock_pct": 0.0, "susde_market_beta": 1.0, "backing_impairment_pct": 0.0,
                 "susde_rate_cut_pct": 0.0, "oracle_lag_hours": 0.0, "pt_implied_apy_shock": 0.0}


def mechanism(node_id: str) -> str:
    kind, _, name = node_id.partition(":")
    if node_id in ETHENA_NODES or kind == "offchain":
        return "usde_backing"
    if node_id == "asset:sUSDe":
        return "susde_exchange_rate"
    if kind == "asset" and name in STABLES:
        return "stablecoin_depeg"
    if kind in ("protocol", "market") or (kind == "asset" and name.startswith("PT-")):
        return "protocol_failure"
    raise ValueError(
        f"node_shock does not price {node_id!r}: use liquidity_crisis for venues and governance_change for oracles.")


@scenario("node_shock")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    node = request.parameters["node_id"]
    loss = request.param("loss_pct", 0.0)
    kind = mechanism(node)

    if kind in ("usde_backing", "susde_exchange_rate"):
        param = "backing_impairment_pct" if kind == "usde_backing" else "susde_rate_cut_pct"
        depeg = replace(request, parameters={
            **NEUTRAL_DEPEG, param: -loss,
            "oracle_pass_through_override": request.parameters.get("oracle_pass_through_override"),
        })
        outcome = usde_depeg.run(portfolio, snapshot, depeg)
    elif kind == "stablecoin_depeg":
        outcome = _stablecoin_depeg(portfolio, snapshot, node.partition(":")[2], loss)
    else:
        outcome = _protocol_failure(portfolio, snapshot, node, loss)

    hit = [i.position_id for i in outcome.impacts if abs(sum(i.loss_components.values())) > 0.005]
    outcome.warnings.append(
        f"Shock on {node} ({kind.replace('_', ' ')}, {loss:.0%}): "
        + (f"reaches {', '.join(hit)}." if hit else "no position is exposed through valuation."))
    return outcome


def _empty(position: Position, gross0: float, debt0: float) -> PositionImpact:
    return PositionImpact(
        position_id=position.position_id, gross_before=gross0, gross_after=gross0, debt_after=debt0,
        net_before=gross0 - debt0,
        loss_components={"market_repricing": 0.0, "backing_impairment": 0.0, "liquidation_penalty": 0.0,
                         "execution_haircut": 0.0},
    )


def _stablecoin_depeg(portfolio: Portfolio, snapshot: Snapshot, symbol: str, loss: float) -> ScenarioOutcome:
    before = MarketState.from_snapshot(snapshot)
    after = replace(before, stables=tuple((s, p * (1 - loss) if s == symbol else p) for s, p in before.stables))
    outcome = ScenarioOutcome(impacts=[], warnings=[
        f"{symbol} depeg priced on the debt side only; any {symbol} held in Ethena's backing is not modeled "
        "(add it as a backing loss)."])
    for position in portfolio.positions:
        gross0, debt0 = position_values(position, before, snapshot)
        gross1, debt1 = position_values(position, after, snapshot)
        impact = _empty(position, gross0, debt0)
        impact.gross_after, impact.debt_after = gross1, debt1
        impact.loss_components["market_repricing"] = (gross0 - debt0) - (gross1 - debt1)
        market = snapshot.market(position.position_id)
        if position.is_borrow and market is not None and position.debt_asset == symbol:
            # Debt oracles are assumed to follow the stablecoin's market price.
            metric = read_metric(market, gross0, gross1, debt0, debt1)
            impact.risk_metric = metric.as_contract()
            impact.warnings.append(f"Debt in {symbol} is worth less in USD: the position gains and its {metric.type} improves.")
        outcome.impacts.append(impact)
    return outcome


def _protocol_failure(portfolio: Portfolio, snapshot: Snapshot, node: str, loss: float) -> ScenarioOutcome:
    kind, _, name = node.partition(":")
    before = MarketState.from_snapshot(snapshot)
    outcome = ScenarioOutcome(impacts=[], warnings=[
        "Protocol failure loss is an assumed share of gross value, not a modeled exploit."])
    for position in portfolio.positions:
        gross0, debt0 = position_values(position, before, snapshot)
        impact = _empty(position, gross0, debt0)
        hit = ((kind == "protocol" and position.protocol == name)
               or (kind == "market" and position.position_id == name)
               or (kind == "asset" and name in (position.asset_symbol, position.collateral_asset)))
        if hit:
            lost = gross0 * loss
            # Limited liability: a borrower whose collateral is gone defaults on the debt.
            capped = min(lost, max(gross0 - debt0, 0.0)) if position.is_borrow else lost
            impact.gross_after = gross0 - lost
            impact.debt_after = debt0 - (lost - capped)  # debt written off once collateral < debt
            impact.loss_components["protocol_failure"] = capped
            if capped < lost:
                impact.warnings.append(
                    f"Collateral loss {lost:,.0f} USD capped at net equity: the debt is not repaid beyond the collateral.")
        else:
            impact.loss_components["protocol_failure"] = 0.0
        outcome.impacts.append(impact)
    return outcome
