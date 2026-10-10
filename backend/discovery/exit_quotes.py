"""Executable exit quote curves at cascade sizes (KyberSwap aggregator, the route P1's venues adapter uses).

Liquidations sell collateral far beyond a position's own size: real Morpho loopers hold 100m+ of
USDe/sUSDe-backed debt. The engine interpolates the loss on `exit_venues.*.quotes` and only
extrapolates beyond the largest quote (flagged), so the curve must reach cascade sizes.

Each quote: sell `size_tokens` of the asset for the stablecoin, all-in (route fees and slippage),
loss_pct in percent versus the snapshot price. Aggregator data is time-stamped, not block-pinned.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / "adapters" / "registry" / "ethereum.json"
SIZES_USD = (500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000, 150_000_000)


def _registry() -> dict:
    return json.loads(REGISTRY.read_text())


def _route(sell: str, buy: str, amount_raw: int) -> dict:
    agg = _registry()["aggregator"]
    query = urllib.parse.urlencode({"tokenIn": sell, "tokenOut": buy, "amountIn": str(amount_raw)})
    request = urllib.request.Request(f"{agg['routes_api']}?{query}",
                                     headers={"x-client-id": agg["client_id"], "user-agent": "defi-contagion-discovery/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        summary = json.loads(response.read())["data"]["routeSummary"]
    if not summary or not summary.get("amountOut"):
        raise RuntimeError(f"no route {sell} -> {buy}")
    return summary


def quote_curve(asset: str, asset_price_usd: float, stable: str = "USDC", stable_price_usd: float = 1.0,
                sizes_usd: tuple[int, ...] = SIZES_USD) -> dict:
    """An exit_venues entry (snapshot schema) with executable quotes from 0.5m to 150m USD."""
    tokens = _registry()["tokens"]
    sell, buy = tokens[asset]["address"], tokens[stable]["address"]
    quotes, gas = [], None
    for size_usd in sizes_usd:
        size_tokens = size_usd / asset_price_usd
        summary = _route(sell, buy, int(size_tokens * 10**18))
        proceeds = int(summary["amountOut"]) / 10**6 * stable_price_usd
        value = size_tokens * asset_price_usd
        quotes.append({
            "size_tokens": f"{size_tokens:.2f}",
            "size_usd": f"{value:.2f}",
            "proceeds_usd": f"{proceeds:.2f}",
            "loss_pct": f"{max(0.0, (1 - proceeds / value) * 100):.4f}",  # small orders can beat the reference price
            "positions": [],
        })
        gas = float(summary["gasUsd"]) if summary.get("gasUsd") else gas
        time.sleep(0.3)  # stay polite with the public aggregator
    return {
        "asset": asset,
        "quote_method": "executable_quote",
        "effective_depth_usd": f"{_proxy_depth(quotes):.2f}",
        "fee_rate": "0",
        "gas_usd": f"{gas or 0:.2f}",
        "venue_address": None,
        "source_type": "observed",
        "field_sources": {"effective_depth_usd": "derived", "fee_rate": "derived"},
        "quotes": quotes,
    }


def _proxy_depth(quotes: list[dict]) -> float:
    """Constant-product depth through the first quote with a real loss (fallback for the proxy users)."""
    for q in quotes:
        loss = float(q["loss_pct"]) / 100
        if loss >= 0.001:
            size = float(q["size_usd"])
            return size * (1 - loss) / loss
    return float(quotes[-1]["size_usd"]) * 1000
