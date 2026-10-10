import json
from functools import lru_cache
from pathlib import Path

import pytest

from backend.discovery.service import discover

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"
CASSETTES = HERE.parent / "cassettes"
FIXTURES = HERE.parents[2] / "contracts" / "fixtures"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


@lru_cache(maxsize=None)
def _replay(name: str) -> tuple[dict, dict, dict]:
    portfolio = load(EXAMPLES / f"{name}.json")
    graph, snapshot = discover(portfolio, "replay", cassette=CASSETTES / f"{name}.json")
    return portfolio, graph, snapshot


@pytest.fixture
def replay():
    """replay(name) -> (portfolio, graph, snapshot), offline from the recorded cassette (validated on the way)."""
    return _replay


def edges_of(graph: dict, source: str | None = None, relation: str | None = None) -> list[dict]:
    return [
        e
        for e in graph["edges"]
        if (source is None or e["source"] == source) and (relation is None or e["relation"] == relation)
    ]


def node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)
