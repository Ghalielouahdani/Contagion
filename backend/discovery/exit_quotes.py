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


PENDLE_SIZES_USD = (250_000, 500_000, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000)


def _pendle_route(pt: str, stable: str, amount_raw: int) -> int:
    registry = _registry()
    url = registry["protocols"]["pendle"]["convert_api"].format(chain_id=1)
    query = urllib.parse.urlencode({
        "receiver": registry["aggregator"]["quote_receiver"], "slippage": "0.01", "enableAggregator": "true",
        "tokensIn": pt, "tokensOut": stable, "amountsIn": str(amount_raw),
    })
    request = urllib.request.Request(f"{url}?{query}", headers={"user-agent": "defi-contagion-discovery/0.1"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return int(json.loads(response.read())["routes"][0]["outputs"][0]["amount"])


def pendle_quote_curve(pt_address: str, pt_symbol: str, pt_price_usd: float, stable: str = "USDC",
                       stable_price_usd: float = 1.0, sizes_usd: tuple[int, ...] = PENDLE_SIZES_USD) -> dict:
    """An exit_venues entry from Pendle router quotes (PT -> stable), the route P1's venues adapter uses.

    The Pendle AMM concentrates liquidity around the implied rate, so a constant-product proxy on total pool
    liquidity overstates the impact by orders of magnitude. Sizes stop at the first one the router cannot route;
    beyond the largest quote the engine extrapolates and flags it."""
    buy = _registry()["tokens"][stable]["address"]
    quotes = []
    for size_usd in sizes_usd:
        size_tokens = size_usd / pt_price_usd
        try:
            proceeds = _pendle_route(pt_address, buy, int(size_tokens * 10**18)) / 10**6 * stable_price_usd
        except Exception:  # noqa: BLE001 - no route at this size: the curve ends here
            break
        value = size_tokens * pt_price_usd
        quotes.append({"size_tokens": f"{size_tokens:.2f}", "size_usd": f"{value:.2f}", "proceeds_usd": f"{proceeds:.2f}",
                       "loss_pct": f"{max(0.0, (1 - proceeds / value) * 100):.4f}", "positions": []})
        time.sleep(0.3)
    if not quotes:
        raise RuntimeError(f"no Pendle route for {pt_symbol}")
    return {
        "asset": pt_symbol, "quote_method": "executable_quote", "effective_depth_usd": f"{_proxy_depth(quotes):.2f}",
        "fee_rate": "0", "gas_usd": "0", "venue_address": None, "source_type": "observed",
        "field_sources": {"effective_depth_usd": "derived", "fee_rate": "derived", "gas_usd": "assumed"}, "quotes": quotes,
    }
