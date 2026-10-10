"""The engine must reproduce the golden fixtures exactly (numbers and flags; warning text is free)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk import simulate
from backend.risk.tests.conftest import load

SCHEMAS = Path(__file__).resolve().parents[3] / "contracts" / "schemas" / "v1"


def assert_same(actual, expected, path="result"):
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key == "warnings":
                continue
            assert key in actual, f"{path}.{key} missing"
            assert_same(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_same(a, e, f"{path}[{i}]")
    elif isinstance(expected, str) and isinstance(actual, str) and _is_number(expected):
        assert Decimal(actual) == Decimal(expected), f"{path}: {actual} != {expected}"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def _is_number(s: str) -> bool:
    try:
        Decimal(s)
        return True
    except ArithmeticError:
        return False


@pytest.mark.parametrize("request_name, golden_name", [
    ("scenario_request", "risk_result"),
    ("scenario_request_liquidity", "risk_result_liquidity"),
])
def test_reproduces_golden_fixture(request_name, golden_name):
    result = simulate(load("portfolio"), load("market_snapshot"), load(request_name), load("dependency_graph"))
    assert_same(result, load(golden_name))


@pytest.mark.parametrize("request_name", ["scenario_request", "scenario_request_liquidity"])
def test_output_validates_against_schema(request_name):
    registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((SCHEMAS / "risk_result.schema.json").read_text()), registry=registry)
    result = simulate(load("portfolio"), load("market_snapshot"), load(request_name))
    errors = [e.message for e in validator.iter_errors(result)]
    assert not errors, errors
