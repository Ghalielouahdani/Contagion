"""Dependency discovery (owner: P1).

    from backend.discovery import discover
    graph, snapshot = discover(portfolio, mode="fixture" | "live" | "replay", cassette=Path(...))

See README.md in this folder.
"""

from __future__ import annotations


def discover(portfolio: dict, mode: str = "fixture", **kwargs) -> tuple[dict, dict]:
    from backend.discovery.service import discover as _discover

    return _discover(portfolio, mode, **kwargs)


def impacted_by(graph: dict, component: str, **kwargs) -> list[dict]:
    from backend.discovery.query import impacted_by as _impacted_by

    return _impacted_by(graph, component, **kwargs)
