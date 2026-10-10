"""Every fixture set validates against schema v1 and keeps its ids consistent across files."""

import json
from pathlib import Path

import pytest

from backend.discovery.validation import consistency_errors, schema_errors

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "fixtures"
SETS = sorted(p.parent for p in FIXTURES.glob("*/manifest.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("folder", SETS, ids=lambda p: p.name)
def test_fixture_files_match_their_schemas(folder):
    manifest = _load(folder / "manifest.json")
    assert not schema_errors(manifest, "fixture_set.schema.json")
    for spec in manifest["files"].values():
        schema = spec["schema"].split("schemas/v1/", 1)[1]
        assert schema_errors(_load(folder / spec["path"]), schema) == [], f"{folder.name}/{spec['path']}"


@pytest.mark.parametrize("folder", SETS, ids=lambda p: p.name)
def test_fixture_ids_are_consistent(folder):
    manifest = _load(folder / "manifest.json")
    ids, files = manifest["ids"], manifest["files"]
    docs = {name: _load(folder / spec["path"]) for name, spec in files.items()}
    assert docs["portfolio"]["portfolio_id"] == ids["portfolio_id"]
    assert docs["dependency_graph"]["graph_id"] == ids["graph_id"]
    assert docs["market_snapshot"]["snapshot_id"] == ids["snapshot_id"]
    for name, doc in docs.items():
        if name.startswith("scenario_request"):
            assert (doc["portfolio_id"], doc["graph_id"], doc["snapshot_id"]) == (
                ids["portfolio_id"],
                ids["graph_id"],
                ids["snapshot_id"],
            )


def test_live_fixture_set_is_internally_consistent():
    folder = FIXTURES / "live_ethena_01"
    errors = consistency_errors(
        _load(folder / "portfolio.json"),
        _load(folder / "dependency_graph.json"),
        _load(folder / "market_snapshot.json"),
    )
    assert errors == []
