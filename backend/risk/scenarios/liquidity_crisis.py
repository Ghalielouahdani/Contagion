"""Scenario B: liquidity crisis (blueprint section 7.2).

Mark value is unchanged (unless a fundamental shock is set); executable value is what a
full exit would realise in crisis depth. Positions exit alone; the portfolio total prices
a joint exit per shared venue and reports the difference as shared_liquidity_penalty.
"""

from __future__ import annotations

from backend.risk import lending
from backend.risk import trace as T
from backend.risk.liquidity import coverage_note, exit_cost, group_by_venue, joint_haircuts, trace_exit
from backend.risk.model import Portfolio, PositionImpact, ScenarioOutcome, ScenarioRequest, Snapshot
from backend.risk.pricing import MarketState, position_values
from backend.risk.scenarios import scenario


@scenario("liquidity_crisis")
def run(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest) -> ScenarioOutcome:
    reduction = request.param("exit_liquidity_reduction_pct", 0.0)
    fundamental = request.param("fundamental_value_shock_pct", 0.0)

    before = MarketState.from_snapshot(snapshot)
    after = before.shocked(fundamental_shock=fundamental)
    k = 1 - reduction  # share of normal depth left in the crisis

    outcome = ScenarioOutcome(impacts=[])
    exits: list[tuple[str, float]] = []
    standalone: dict[str, float] = {}

    for position in portfolio.positions:
        gross0, debt0 = position_values(position, before, snapshot)
        gross1, debt1 = position_values(position, after, snapshot)
        impact = PositionImpact(
            position_id=position.position_id,
            gross_before=gross0,
            gross_after=gross1,
            debt_after=debt1,
            net_before=gross0 - debt0,
            loss_components={
                "market_repricing": (gross0 - debt0) - (gross1 - debt1),
                "backing_impairment": 0.0,
                "liquidation_penalty": 0.0,
                "execution_haircut": 0.0,
            },
        )
        if lending.is_lender(position):
            note, missing = lending.exit_note(position, snapshot, reduction)
            impact.warnings.append(note)
            impact.insufficient_data = missing
            outcome.impacts.append(impact)
            continue
        venue = snapshot.venues.get(position.exit_venue_id)
        if venue is None:
            impact.insufficient_data = True
            impact.warnings.append(f"No exit venue data for {position.exit_venue_id}; executable value not computed.")
        else:
            # A borrow position exits by selling its collateral (pro-rata unwind at x = 100%).
            cost = exit_cost(venue, gross1, k)
            trace_exit(impact.trace, venue, gross1, k, T.venue_source(snapshot, venue.venue_id))
            impact.loss_components["execution_haircut"] = cost
            impact.executable_after = gross1 - cost
            standalone[position.position_id] = cost
            exits.append((venue.venue_id, gross1))
            note = "Proxy depth; standalone exit." if not venue.curve else "Priced on executable quotes; standalone exit."
            extrapolated = coverage_note(venue, gross1, k)
            if extrapolated:
                impact.warnings.append(extrapolated)
            sharing = [p.position_id for p in portfolio.positions
                       if p.exit_venue_id == venue.venue_id and p.position_id != position.position_id]
            if sharing:
                note += f" Shares {venue.venue_id} with {', '.join(sharing)}."
            impact.warnings.append(note)
        outcome.impacts.append(impact)

    joint = joint_haircuts(group_by_venue(exits), snapshot.venues, k)
    outcome.shared_liquidity_penalty = sum(joint.values()) - sum(standalone.values())
    T.step(outcome.trace, "shared_liquidity_penalty", "Shared exit venues: selling together costs more",
           "sum over venues of cost(sum of sizes) - sum of each position's standalone cost",
           [T.inp("joint cost", sum(joint.values()), T.USD, T.DERIVED),
            T.inp("standalone costs", sum(standalone.values()), T.USD, T.DERIVED)],
           outcome.shared_liquidity_penalty, T.USD,
           note="Exists only at portfolio level: no single position carries it.")
    if outcome.shared_liquidity_penalty > 0:
        outcome.warnings.append(
            "Portfolio total uses a joint exit per shared venue; it exceeds the sum of position losses by shared_liquidity_penalty_usd."
        )
    return outcome
