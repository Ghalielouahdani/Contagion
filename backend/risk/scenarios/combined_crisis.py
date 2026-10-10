"""Scenario C: depeg and liquidity crisis at once (the real crisis: A and B do not happen apart).

Order of events:
1. USDe depegs (scenario A): mark repricing, backing loss, oracle-driven liquidations.
2. Liquidators sell the collateral they seize into the position's exit venue, at crisis depth.
3. The fund exits what is left, queued behind that forced selling: its haircut is the marginal
   cost haircut(forced + size) - haircut(forced), so a liquidation on a shared venue makes every
   other exit on that venue more expensive. That is contagion through liquidity, in dollars.

The comparison block reports the same crisis with no liquidation selling ahead of the fund:
the excess is the pure contagion through the shared exit venues. A warning also gives what
adding A and B run separately would say (B haircuts pre-depeg values, so the sum is off).
One round only: the price impact of forced selling does not feed back into oracles here
(that loop is the liquidation cascade, roadmap step 4).
"""

from __future__ import annotations

from dataclasses import replace

from backend.risk import lending
from backend.risk import trace as T
from backend.risk.liquidity import coverage_note, exit_cost, trace_exit
from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.scenarios import liquidity_crisis, scenario, usde_depeg


def queued_haircut(venue, size, forced, depth_factor):
    """Execution loss of selling `size` after `forced` has already been sold into the same venue."""
    return exit_cost(venue, forced + size, depth_factor) - exit_cost(venue, forced, depth_factor)


def seized_collateral(impact) -> float:
    """Market value liquidators take from a liquidatable position: repaid debt plus their incentive."""
    penalty = impact.loss_components["liquidation_penalty"]
    if penalty <= 0:
        return 0.0
    metric = impact.internals["metric"]
    repaid = metric.close_factor * impact.debt_after
    return min(repaid * (1 + metric.liquidation_incentive), impact.gross_after)


@scenario("combined_crisis")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    outcome = _run(portfolio, snapshot, request, forced_selling=True)
    without = _run(portfolio, snapshot, request, forced_selling=False)
    outcome.comparison = {
        "runs": [{"run_id": "without_liquidation_selling",
                  "description": "Same depeg and liquidity loss, liquidators' sales not queued ahead of the fund's exit.",
                  "total_loss": _total(without)}],
        "excess_meaning": "Contagion through liquidity: extra exit cost because liquidations sell into the same venues first.",
    }
    depeg_only = usde_depeg.run(portfolio, snapshot, request)
    liquidity_only = liquidity_crisis.run(portfolio, snapshot, replace(request, parameters={
        "exit_liquidity_reduction_pct": request.param("exit_liquidity_reduction_pct", 0.0),
        "fundamental_value_shock_pct": 0.0,
    }))
    naive = _total(depeg_only) + _total(liquidity_only)
    combined = _total(outcome)
    outcome.warnings.append(
        f"Running the depeg ({_total(depeg_only):,.0f} USD) and the liquidity crisis ({_total(liquidity_only):,.0f} USD) "
        f"separately and adding them gives {naive:,.0f} USD, {'over' if naive > combined else 'under'}stating the joint "
        f"loss by {abs(naive - combined):,.0f} USD: the separate liquidity run sells pre-depeg values.")
    return outcome


def _run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, forced_selling: bool) -> ScenarioOutcome:
    reduction = request.param("exit_liquidity_reduction_pct", 0.0)
    k = 1 - reduction  # share of normal depth left in the crisis

    outcome = usde_depeg.run(portfolio, snapshot, request)
    impacts = {i.position_id: i for i in outcome.impacts}

    forced: dict[str, float] = {}
    for position in portfolio.positions:
        seized = seized_collateral(impacts[position.position_id])
        if forced_selling and seized > 0 and position.exit_venue_id in snapshot.venues:
            forced[position.exit_venue_id] = forced.get(position.exit_venue_id, 0.0) + seized

    exits: dict[str, float] = {}
    standalone = 0.0
    for position in portfolio.positions:
        impact = impacts[position.position_id]
        if lending.is_lender(position):
            note, missing = lending.exit_note(position, snapshot, reduction)
            impact.warnings.append(note)
            impact.insufficient_data = impact.insufficient_data or missing
            continue
        venue = snapshot.venues.get(position.exit_venue_id)
        if venue is None:
            impact.insufficient_data = True
            impact.warnings.append(f"No exit venue data for {position.exit_venue_id}; executable value not computed.")
            continue
        # A liquidated borrow only has the collateral the liquidators left to sell.
        size = impact.gross_after - seized_collateral(impact)
        ahead = forced.get(venue.venue_id, 0.0)
        cost = queued_haircut(venue, size, ahead, k)
        trace_exit(impact.trace, venue, size, k, T.venue_source(snapshot, venue.venue_id), ahead)
        extrapolated = coverage_note(venue, ahead + size, k)
        if extrapolated:
            impact.warnings.append(extrapolated)
        impact.loss_components["execution_haircut"] = cost
        impact.executable_after = impact.gross_after - cost
        standalone += cost
        exits[venue.venue_id] = exits.get(venue.venue_id, 0.0) + size
        if ahead > 0:
            impact.warnings.append(
                f"Exit queued behind {ahead:,.0f} USD of liquidation selling on {venue.venue_id}; "
                f"without it the haircut would be {exit_cost(venue, size, k):,.0f} USD.")

    joint = sum(queued_haircut(snapshot.venues[vid], size, forced.get(vid, 0.0), k) for vid, size in exits.items())
    outcome.shared_liquidity_penalty = joint - standalone
    T.step(outcome.trace, "shared_liquidity_penalty", "Shared exit venues: selling together costs more",
           "sum over venues of the joint marginal cost behind liquidations - sum of standalone costs",
           [T.inp("joint cost", joint, T.USD, T.DERIVED), T.inp("standalone costs", standalone, T.USD, T.DERIVED)],
           outcome.shared_liquidity_penalty, T.USD, note="Exists only at portfolio level: no single position carries it.")
    if outcome.shared_liquidity_penalty > 0:
        outcome.warnings.append(
            "Portfolio total uses a joint exit per shared venue, behind the liquidation selling; it exceeds "
            "the sum of position losses by shared_liquidity_penalty_usd.")
    if forced:
        outcome.warnings.append(
            "Liquidators sell seized collateral into the crisis venues before the fund exits (one round; the price "
            "impact does not feed back into oracles).")
    return outcome


def _total(outcome: ScenarioOutcome) -> float:
    return sum(sum(i.loss_components.values()) for i in outcome.impacts) + outcome.shared_liquidity_penalty
