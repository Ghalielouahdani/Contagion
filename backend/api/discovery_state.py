"""Which graph and snapshot the API computes on, per fixture set: stored, replayed or live.

/discover?discovery=stored  -> the set's stored dependency_graph / market_snapshot (default, instant)
/discover?discovery=replay  -> P1 discovery re-run offline from backend/discovery/cassettes/<set>.json
/discover?discovery=live    -> P1 discovery against Ethereum now (ETH_RPC_URL; seconds to minutes)

A replayed or live discovery becomes the set's *active* inputs: /simulate, /analyze and /decide
then compute on that graph and snapshot, so one /discover call drives the whole chain end to end.
In-memory and per process; /discover?discovery=stored resets a set to its stored files.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from backend.discovery import discover

CASSETTES = Path(__file__).resolve().parents[1] / "discovery" / "cassettes"
MODES = ("stored", "replay", "live")


@dataclass
class ActiveInputs:
    mode: str
    graph: dict
    snapshot: dict
    warnings: list[str] = field(default_factory=list)


_active: dict[str, ActiveInputs] = {}


def run(set_name: str, files: dict, mode: str) -> ActiveInputs:
    if mode not in MODES:
        raise ValueError(f"discovery must be one of {MODES}, got {mode!r}")
    if mode == "stored":
        _active.pop(set_name, None)
        return ActiveInputs("stored", files["dependency_graph"], files["market_snapshot"])
    kwargs = {"graph_id": files["dependency_graph"]["graph_id"], "snapshot_id": files["market_snapshot"]["snapshot_id"]}
    if mode == "replay":
        cassette = CASSETTES / f"{set_name}.json"
        if not cassette.is_file():
            raise ValueError(f"no recorded discovery for set {set_name!r} (expected {cassette.name}); use discovery=stored or live")
        kwargs["cassette"] = cassette
    graph, snapshot = discover(files["portfolio"], mode, **kwargs)
    active = ActiveInputs(mode, graph, snapshot)
    if snapshot.get("block_number") != files["market_snapshot"].get("block_number"):
        active.warnings.append(
            f"Snapshot re-discovered at block {snapshot.get('block_number')} "
            f"(stored set: {files['market_snapshot'].get('block_number')}); stored risk results no longer apply."
        )
    _active[set_name] = active
    return active


def current(set_name: str, files: dict) -> ActiveInputs:
    return _active.get(set_name) or ActiveInputs("stored", files["dependency_graph"], files["market_snapshot"])


def readdress(request: dict, active: ActiveInputs) -> dict:
    """Point a scenario request at the active graph and snapshot (ids may change after a live discovery)."""
    request = copy.deepcopy(request)
    request["graph_id"] = active.graph["graph_id"]
    request["snapshot_id"] = active.snapshot["snapshot_id"]
    return request


def reset() -> None:
    _active.clear()
