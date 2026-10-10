"""Calculation trace: every published number carries the steps that produced it.

A step is one formula applied to named inputs, each with its value, unit and provenance
(snapshot source_type, "user_scenario" for a scenario parameter, "derived" for a previous
step, "protocol_rule" for a protocol constant). The risk result publishes the steps per
position and for the portfolio, so a risk manager can follow a loss from the inputs to the
total without reading code. Steps are recorded while the engine computes, never rebuilt
afterwards, so the trace cannot drift from the numbers.
"""

from __future__ import annotations

from typing import Any

USD, PRICE, RATIO, PCT, TOKENS, DAYS, FLAG = "usd", "price", "ratio", "pct", "tokens", "days", "flag"
SCENARIO = "user_scenario"
DERIVED = "derived"
RULE = "protocol_rule"


def inp(name: str, value: Any, unit: str, source: str) -> dict:
    return {"name": name, "value": value, "unit": unit, "source": source}


def step(trace: list[dict], step_id: str, label: str, formula: str, inputs: list[dict], result: Any, unit: str,
         note: str | None = None, rows: list[dict] | None = None) -> Any:
    """Append one step to `trace` and return its result (so it can be used inline)."""
    entry = {"id": step_id, "label": label, "formula": formula, "inputs": inputs, "result": {"value": result, "unit": unit}}
    if note:
        entry["note"] = note
    if rows:
        entry["rows"] = rows
    trace.append(entry)
    return result


def price_source(snapshot, symbol: str) -> str:
    return snapshot.sources.get(f"price:{symbol}", "assumed")


def market_source(snapshot, key: str) -> str:
    return snapshot.sources.get(f"market:{key}", "assumed")


def venue_source(snapshot, venue_id: str) -> str:
    return snapshot.sources.get(f"venue:{venue_id}", "assumed")


def yield_source(snapshot, key: str) -> str:
    return snapshot.sources.get(f"yield:{key}", "assumed")


def snapshot_rate_source(snapshot) -> str:
    return snapshot.sources.get("rate:sUSDe_USDe", "assumed")
