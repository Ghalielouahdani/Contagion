"""Connect P3 decisions to the current risk result and snapshot exit-pricing model."""
from __future__ import annotations

import copy
from decimal import Decimal as D

from backend.execution.decision import decide_position
from backend.execution.exit_cost import ExitCostEstimator
from backend.risk import lending, simulate
from backend.risk.liquidity import coverage, coverage_note, exit_cost
from backend.risk.model import Portfolio, Snapshot


def decide(portfolio: dict, snapshot: dict, request: dict, position_id: str,
           risk_result: dict | None = None) -> dict:
    """Same JSON decision contract as the dashboard; consume a supplied risk run when available."""
    result = risk_result if risk_result is not None else simulate(portfolio, snapshot, request)
    if request['snapshot_id'] != snapshot['snapshot_id']:
        raise ValueError('Decision request and snapshot IDs do not match')
    if result['provenance']['input_snapshot_id'] != snapshot['snapshot_id']:
        raise ValueError('Risk result and decision snapshot IDs do not match')
    valued = copy.deepcopy(portfolio)
    prepared = copy.deepcopy(snapshot)
    impacts = {p['position_id']: p for p in result['positions']}
    for position in valued['positions']:
        impact = impacts[position['position_id']]
        position['gross_value_usd'] = impact['gross_value_before_usd']
        position['net_equity_usd'] = impact['net_equity_before_usd']
        position['debt_value_usd'] = str(D(impact['gross_value_before_usd']) - D(impact['net_equity_before_usd']))
    model = Snapshot.from_contract(snapshot)
    position = next(p for p in Portfolio.from_contract(portfolio).positions if p.position_id == position_id)
    notes = []
    if lending.is_lender(position):
        market = model.market(position_id)
        available = lending.withdrawable(position, market) if market else None
        impact = impacts[position_id]
        available_usd = (D(str(available)) * D(impact['gross_value_before_usd']) / D(str(position.quantity))
                         if available is not None and position.quantity > 0 else None)
        prepared.setdefault('exit_venues', {})[position.exit_venue_id] = {
            'fee_rate': '0', 'gas_usd': '0', 'quote_method': 'pool_reserves',
        }
        def withdrawal(_vid, _venue, size):
            return D(0) if available_usd is not None and size <= available_usd else None
        estimator = ExitCostEstimator(pool_reserves=withdrawal, proxy=None)
        notes.append('Lender exit is a withdrawal from snapshot idle market liquidity, not a DEX sale. '
                     'Fractions beyond available liquidity are omitted; locked supply is a delay, not a loss. '
                     'Withdrawal fees and gas are not supplied by the snapshot; shown as zero.')
    else:
        def quoted(vid, _venue, size):
            venue = model.venues.get(vid)
            if venue is None or not venue.curve or coverage(venue, float(size)) != 'quoted':
                return None
            return D(str(exit_cost(venue, float(size))))
        def proxy(vid, _venue, size):
            venue = model.venues.get(vid)
            if venue is None or venue.effective_depth_usd <= 0:
                return None
            note = coverage_note(venue, float(size))
            if note and note not in notes:
                notes.append(note)
            return D(str(exit_cost(venue, float(size))))
        estimator = ExitCostEstimator(executable=quoted, proxy=proxy)
    decision = decide_position(valued, prepared, result, request, position_id, estimator=estimator)
    decision['warnings'].extend(notes)
    return decision
