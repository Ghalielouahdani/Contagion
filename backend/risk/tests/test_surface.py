"""Offline risk surface: valid, consistent with the engine and the golden fixtures."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.risk.tests.test_golden import assert_same

ROOT = Path(__file__).resolve().parents[3] / "contracts"


def load(set_name, name):
    return json.loads((ROOT / "fixtures" / set_name / f"{name}.json").read_text())


@pytest.mark.parametrize("set_name", ["demo_ethena_01", "verified_2026_10_10"])
def test_surface_validates_against_schema(set_name):
    registry = Registry()
    for path in (ROOT / "schemas" / "v1").rglob("*.schema.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(json.loads((ROOT / "schemas" / "v1" / "risk_surface.schema.json").read_text()), registry=registry)
    errors = [e.message for e in validator.iter_errors(load(set_name, "risk_surface"))]
    assert not errors, errors[:3]


def point(surface, scenario, value):
    return next(p for p in surface["scenarios"][scenario]["points"] if D(p["value"]) == D(value))


def test_surface_points_match_golden_fixtures():
    surface = load("demo_ethena_01", "risk_surface")
    golden = load("demo_ethena_01", "risk_result")
    golden.pop("contagion")
    for position in golden["positions"]:
        position.pop("contagion")
    assert_same(point(surface, "usde_depeg", "-0.05")["risk_result"], golden)
    assert point(surface, "liquidity_crisis", "0.80")["risk_result"]["portfolio"]["total_conditional_loss_usd"] == "920646.49"


def test_surface_losses_grow_with_the_slider():
    surface = load("demo_ethena_01", "risk_surface")
    for scenario in ("usde_depeg", "liquidity_crisis"):
        totals = [D(p["risk_result"]["portfolio"]["total_conditional_loss_usd"]) for p in surface["scenarios"][scenario]["points"]]
        # Not zero at 0%: the PT yield shock stays on, and an exit costs something even at normal depth.
        assert totals == sorted(totals)
        assert totals[-1] > totals[0]


def test_surface_has_a_decision_per_position_and_point():
    surface = load("demo_ethena_01", "risk_surface")
    ids = {p["position_id"] for p in load("demo_ethena_01", "portfolio")["positions"]}
    for scenario in surface["scenarios"].values():
        for p in scenario["points"]:
            assert set(p["decisions"]) == ids
