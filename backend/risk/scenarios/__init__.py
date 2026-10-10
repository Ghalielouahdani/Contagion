"""Scenario registry. Adding a scenario = one module here + one @scenario line, mirroring
contracts/schemas/v1/scenarios/."""

from __future__ import annotations

from typing import Callable

from backend.risk.model import Portfolio, ScenarioOutcome, ScenarioRequest, Snapshot

ScenarioFn = Callable[[Portfolio, Snapshot, ScenarioRequest], ScenarioOutcome]

REGISTRY: dict[str, ScenarioFn] = {}


def scenario(scenario_id: str) -> Callable[[ScenarioFn], ScenarioFn]:
    def register(fn: ScenarioFn) -> ScenarioFn:
        REGISTRY[scenario_id] = fn
        return fn

    return register


def get(scenario_id: str) -> ScenarioFn:
    if scenario_id not in REGISTRY:
        raise KeyError(f"unknown scenario {scenario_id!r}; registered: {sorted(REGISTRY)}")
    return REGISTRY[scenario_id]


from backend.risk.scenarios import liquidity_crisis, usde_depeg  # noqa: E402,F401  (registers scenarios)
from backend.risk.scenarios import carry_squeeze, combined_crisis, governance_change, node_shock  # noqa: E402,F401
