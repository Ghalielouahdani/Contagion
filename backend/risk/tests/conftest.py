import copy
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "demo_ethena_01"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def portfolio():
    return load("portfolio")


@pytest.fixture
def snapshot():
    return load("market_snapshot")


@pytest.fixture
def graph():
    return load("dependency_graph")


@pytest.fixture
def depeg_request():
    return load("scenario_request")


@pytest.fixture
def liquidity_request():
    return load("scenario_request_liquidity")


def with_params(request: dict, **params) -> dict:
    r = copy.deepcopy(request)
    r["scenario"]["parameters"].update({k: (None if v is None else str(v)) for k, v in params.items()})
    return r


def by_id(result: dict) -> dict:
    return {p["position_id"]: p for p in result["positions"]}
