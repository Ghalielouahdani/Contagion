import copy
import json

import pytest

from backend.execution.decision import FIXTURE_DIR, decide_position, load_contracts


@pytest.fixture
def contracts():
    return load_contracts()


def run(c, position_id="aave_01"):
    return decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], position_id)


def test_aave_01_matches_golden_fixture_field_by_field(contracts):
    golden = json.loads((FIXTURE_DIR / "decision_result.json").read_text())
    got = run(contracts)
    assert list(got) == list(golden)                       # mêmes champs, même ordre
    for key in golden:
        assert got[key] == golden[key], key


def test_inconsistent_request_ids_are_rejected(contracts):
    c = copy.deepcopy(contracts)
    c["risk_result"]["request_id"] = "sim_999"
    with pytest.raises(ValueError, match="request_id"):
        run(c)


def test_unknown_position_is_rejected(contracts):
    with pytest.raises(ValueError, match="nope_01"):
        run(contracts, "nope_01")
