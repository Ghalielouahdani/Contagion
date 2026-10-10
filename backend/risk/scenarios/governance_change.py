"""Scenario E: governance or oracle regime change, then a depeg.

"Your position is safe until someone votes." A risk steward lowers liquidation thresholds
(Aave LT, Morpho LLTV) and/or governance switches a market's oracle (e.g. from an exchange
rate with USDe hardcoded at 1 USD to a market price feed). The change lands, then the
scenario A shock applies to the changed markets.

The comparison block reports the same depeg on today's parameters; the excess is what the
governance change alone costs. Sensitivity already shows these parameters are cliff edges.
"""

from __future__ import annotations

from dataclasses import replace

from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.scenarios import scenario, usde_depeg

# Field holding the liquidation threshold, per market_kind (lending markets only).
THRESHOLD_FIELD = {"aave_v3_reserve": "liquidation_threshold", "morpho_blue_market": "lltv"}


def changed_snapshot(snapshot: Snapshot, request: ScenarioRequest) -> tuple[Snapshot, list[str]]:
    shift = request.param("liquidation_threshold_shift", 0.0)
    switch = request.param("oracle_switch_pass_through")
    targets = request.parameters.get("target_markets")
    markets, notes = dict(snapshot.markets), []
    for pid, market in snapshot.markets.items():
        field = THRESHOLD_FIELD.get(market.get("market_kind"))
        if field is None or (targets is not None and pid not in targets):
            continue
        new = dict(market)
        if shift:
            old = float(market[field])
            new[field] = str(min(max(old + shift, 0.0), 0.99))
            notes.append(f"{pid} {field} {old:g} -> {float(new[field]):g}")
        if switch is not None:
            old = float(market.get("oracle_pass_through", 1.0))
            new["oracle_pass_through"] = str(switch)
            if old != switch:
                notes.append(f"{pid} oracle pass-through {old:g} -> {switch:g}")
        markets[pid] = new
    return replace(snapshot, markets=markets), notes


@scenario("governance_change")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    changed, notes = changed_snapshot(snapshot, request)
    unknown = set(request.parameters.get("target_markets") or ()) - set(snapshot.markets)
    # The oracle switch is expressed through the changed snapshot, never through the depeg override.
    depeg = replace(request, parameters={**request.parameters, "oracle_pass_through_override": None})

    outcome = usde_depeg.run(portfolio, changed, depeg)
    outcome.warnings.append("Governance change applied before the shock: " + ("; ".join(notes) if notes else "no market changed") + ".")
    if unknown:
        outcome.warnings.append(f"target_markets not in the snapshot, ignored: {', '.join(sorted(unknown))}.")

    unchanged = usde_depeg.run(portfolio, snapshot, depeg)
    outcome.comparison = {
        "runs": [{"run_id": "without_governance_change", "description": "Same depeg on today's market parameters.",
                  "total_loss": sum(sum(i.loss_components.values()) for i in unchanged.impacts)}],
        "excess_meaning": "Loss caused by the governance change alone.",
    }
    return outcome
