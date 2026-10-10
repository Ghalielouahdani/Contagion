import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.execution.integration import decide
from backend.risk import simulate
from backend.risk.liquidity import exit_cost
from backend.risk.model import Snapshot

ROOT = Path(__file__).resolve().parents[3] / 'contracts' / 'fixtures'


def inputs(name, suffix=''):
    root = ROOT / name
    load = lambda file: json.loads((root / f'{file}.json').read_text())
    p, s, r = load('portfolio'), load('market_snapshot'), load('scenario_request' + suffix)
    return p, s, r, simulate(p, s, r, load('dependency_graph'))


def test_execution_consumes_exact_risk_run_and_preserves_carry_gains():
    p, s, r, risk = inputs('verified_lending_2026_10_10', '_carry')
    decision = decide(p, s, r, 'lend_susde_01', risk)
    assert decision['simulation_id'] == risk['simulation_id']
    assert D(decision['exit_options'][0]['residual_stress_loss_usd']) == D(risk['positions'][0]['conditional_loss_usd']) < 0


def test_lender_withdrawals_respect_idle_market_liquidity():
    p, s, r, risk = inputs('demo_lending_01')
    s['markets']['lend_usde_01']['total_supply_assets'] = '60000000'
    s['markets']['lend_usde_01']['total_borrow_assets'] = '58500000'
    decision = decide(p, s, r, 'lend_usde_01', risk)
    assert [o['exit_fraction'] for o in decision['exit_options']] == ['0.00', '0.25']
    option = decision['exit_options'][1]
    assert option['quote_status'] == 'pool_reserves'
    assert D(option['price_impact_usd']) == 0
    assert any('withdrawal' in w for w in decision['warnings'])


def test_execution_uses_same_quote_curve_as_risk_with_current_marks():
    p, s, r, risk = inputs('live_ethena_01')
    pid = 'ethena_susde_01'
    decision = decide(p, s, r, pid, risk)
    impact = next(i for i in risk['positions'] if i['position_id'] == pid)
    position = next(i for i in p['positions'] if i['position_id'] == pid)
    venue = Snapshot.from_contract(s).venues[position['exit_venue_id']]
    option = decision['exit_options'][-1]
    assert option['quote_status'] == 'executable'
    expected = D(str(exit_cost(venue, float(impact['gross_value_before_usd'])))).quantize(D('.01'))
    assert abs(D(option['price_impact_usd']) - expected) <= D('.01')


def test_execution_rejects_a_risk_result_from_another_snapshot():
    p, s, r, risk = inputs('demo_ethena_01')
    wrong = copy.deepcopy(risk)
    wrong['provenance']['input_snapshot_id'] = 'snapshot_other'
    with pytest.raises(ValueError, match='snapshot'):
        decide(p, s, r, 'aave_01', wrong)
