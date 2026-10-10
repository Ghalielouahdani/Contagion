"""Schema v1 validation plus the cross-file checks a schema cannot express."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "v1"


@lru_cache(maxsize=1)
def _registry() -> tuple[Registry, dict[str, dict]]:
    by_name, resources = {}, []
    for path in sorted(SCHEMAS.rglob("*.schema.json")):
        schema = json.loads(path.read_text())
        by_name[path.relative_to(SCHEMAS).as_posix()] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources), by_name


def schema_errors(document: dict, schema: str) -> list[str]:
    """schema: file name under contracts/schemas/v1, e.g. 'dependency_graph.schema.json'."""
    registry, by_name = _registry()
    validator = Draft202012Validator(by_name[schema], registry=registry)
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]


def consistency_errors(portfolio: dict, graph: dict, snapshot: dict) -> list[str]:
    errors = []
    ids = [n["id"] for n in graph["nodes"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate node ids")
    known = set(ids)
    for e in graph["edges"]:
        for end in (e["source"], e["target"]):
            if end not in known:
                errors.append(f"{e['id']}: endpoint {end} is not a node")
    positions = {p["position_id"]: p for p in portfolio["positions"]}
    exits = {e["source"] for e in graph["edges"] if e["relation"] == "exits_via"}
    for pid, p in positions.items():
        if f"position:{pid}" not in known:
            errors.append(f"position {pid} missing from the graph")
        elif f"position:{pid}" not in exits:
            errors.append(f"position {pid} has no exits_via edge")
        if p["exit_venue_id"] not in snapshot["exit_venues"]:
            errors.append(f"venue {p['exit_venue_id']} of {pid} missing from the snapshot")
    for pid in snapshot["markets"]:
        if pid not in positions:
            errors.append(f"snapshot market keyed by unknown position {pid}")
    for doc in (graph, snapshot):
        if "TO_VERIFY" in json.dumps(doc):
            errors.append(f"{doc.get('graph_id') or doc.get('snapshot_id')}: TO_VERIFY placeholder left")
    if graph["portfolio_id"] != portfolio["portfolio_id"]:
        errors.append("graph.portfolio_id does not match the portfolio")
    return errors
