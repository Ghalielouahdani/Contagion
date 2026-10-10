"""Exit venues: where each position would be sold, and how deep that route is.

For every portfolio venue the resolver quotes the venue's joint size (every position that
exits there, sold at once) and converts the quoted loss into the constant-product depth the
risk engine's proxy uses:

    haircut = size^2 / (depth + size)   =>   depth = size^2 / haircut - size

- size is marked at the snapshot price of the sold asset, proceeds at the snapshot price of
  the received asset, so the haircut is measured against the same mark P2 uses;
- a Pendle PT is quoted through Pendle's own router API (PT -> SY on its AMM, then out);
  other assets through a DEX aggregator. Fees are inside the quote, so fee_rate is 0;
- no quote: Pendle PT -> AMM liquidity from the Pendle API (pool_reserves); otherwise the
  team's assumed proxy, flagged as such. Quotes are time-stamped, not block-pinned.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.adapters.base import Ctx, decimal_str
from backend.adapters.sources import SourceError

NO_IMPACT_DEPTH_MULTIPLE = 10_000  # quote shows no measurable loss: depth capped at 10,000x the size


@dataclass
class Leg:
    position_id: str
    sell_token: str
    quantity: Decimal  # token units
    quote_token: str


@dataclass
class Quote:
    source: str  # "pendle_router" | "aggregator"
    url: str
    out_tokens: Decimal
    exchanges: list[str]
    pools: list[str]
    gas_units: int | None = None
    gas_usd: float | None = None
    in_usd: float | None = None  # the quoting service's own valuation, used only without a snapshot price
    out_usd: float | None = None


def resolve(ctx: Ctx, venue_id: str, legs: list[Leg], assumed: dict | None, prices: dict[str, float]) -> dict | None:
    sell = legs[0].sell_token
    if any(leg.sell_token != sell for leg in legs):
        ctx.warnings.append(f"{venue_id}: positions sell different assets through one venue; quoting {sell} only")
    buy = legs[0].quote_token
    sell_node, buy_node = ctx.asset(sell), ctx.asset(buy)
    sell_sym, buy_sym = ctx.graph.nodes[sell_node].label, ctx.graph.nodes[buy_node].label
    size_tokens = sum((leg.quantity for leg in legs if leg.sell_token == sell), Decimal(0))
    venue = ctx.graph.node(
        venue_id,
        "venue",
        f"{sell_sym} -> {buy_sym} exit route",
        chain_id=ctx.chain_id,
        sell_asset=sell,
        quote_asset=buy,
        joint_size_tokens=decimal_str(size_tokens, 6),
        positions=[leg.position_id for leg in legs],
    )

    pendle_market = (ctx.facts.get("pt_markets") or {}).get(sell)
    if pendle_market:
        ctx.graph.edge(
            venue,
            ctx.facts["pendle_markets"][pendle_market]["node"],
            "routes_through",
            "exit_liquidity",
            ctx.onchain(
                None,
                "before expiry a PT exits only by selling into its Pendle AMM",
                call="readTokens()",
                reference=pendle_market,
            ),
            "verified",
        )
    source = _pendle_quote if pendle_market else _aggregator_quote
    quote = source(ctx, sell, buy, size_tokens)
    entry = _from_quote(ctx, venue, sell_node, sell_sym, buy_sym, size_tokens, quote, legs, prices) if quote else None
    if entry:
        if sell_sym in prices and buy_sym in prices:
            entry["quotes"] = _curve(ctx, legs, sell, buy, sell_sym, buy_sym, size_tokens, quote, source, prices)
            _warn_misfit(ctx, venue_id, entry)
        return entry
    if pendle_market and ctx.facts["pendle_markets"][pendle_market]["liquidity_usd"]:
        return _from_pendle_pool(ctx, venue, sell_node, sell_sym, pendle_market, legs)
    return _assumed(ctx, venue, venue_id, sell_node, sell_sym, legs, assumed)


def _curve(
    ctx: Ctx,
    legs: list[Leg],
    sell: str,
    buy: str,
    sell_sym: str,
    buy_sym: str,
    joint: Decimal,
    joint_quote: Quote,
    source,
    prices: dict[str, float],
) -> list[dict]:
    """Quotes at each position's standalone size and at the joint size (the one depth is calibrated on)."""
    sizes: dict[Decimal, list[str]] = {}
    for leg in legs:
        sizes.setdefault(leg.quantity, []).append(leg.position_id)
    rows = []
    for size, owners in sorted(sizes.items()) + ([(joint, [leg.position_id for leg in legs])] if len(legs) > 1 else []):
        quote = joint_quote if size == joint else source(ctx, sell, buy, size)
        if quote is None:
            continue
        size_usd, out_usd = float(size) * prices[sell_sym], float(quote.out_tokens) * prices[buy_sym]
        rows.append(
            {
                "size_tokens": decimal_str(size, 6),
                "size_usd": decimal_str(size_usd, 2),
                "proceeds_usd": decimal_str(out_usd, 2),
                "loss_pct": decimal_str((size_usd - out_usd) / size_usd * 100, 4),
                "positions": owners,
            }
        )
    return rows


def _warn_misfit(ctx: Ctx, venue_id: str, entry: dict) -> None:
    """Flag when the single constant-product depth misprices the standalone quotes by a wide margin."""
    depth = float(entry["effective_depth_usd"])
    for row in entry["quotes"][:-1] if len(entry["quotes"]) > 1 else []:
        size = float(row["size_usd"])
        proxy = size / (depth + size) * 100
        quoted = float(row["loss_pct"])
        if abs(proxy - quoted) > max(0.5, quoted):
            ctx.warnings.append(
                f"{venue_id}: depth is calibrated on the joint size; for {', '.join(row['positions'])} "
                f"alone the proxy gives {proxy:.2f}% loss vs {quoted:.2f}% quoted (see quotes)"
            )


# quote sources ---------------------------------------------------------------------------
def _slim_convert(body: dict) -> dict:
    routes = []
    for r in body.get("routes") or []:
        data = r.get("data") or {}
        routes.append(
            {
                "outputs": r.get("outputs"),
                "data": {k: data.get(k) for k in ("aggregatorType", "priceImpact", "fee", "gasUsed")},
                "tx": {"gas": (r.get("tx") or {}).get("gas")},
            }
        )
    return {"routes": routes}


def _slim_routes(body: dict) -> dict:
    s = (body.get("data") or {}).get("routeSummary")
    if not s:
        return {"message": body.get("message"), "data": None}
    keep = ("amountIn", "amountInUsd", "amountOut", "amountOutUsd", "gasUsd")
    route = [[{"pool": h.get("pool"), "exchange": h.get("exchange")} for h in path] for path in s.get("route") or []]
    return {"message": body.get("message"), "data": {"routeSummary": {**{k: s.get(k) for k in keep}, "route": route}}}


def _pendle_quote(ctx: Ctx, sell: str, buy: str, size_tokens: Decimal) -> Quote | None:
    url = ctx.registry.protocol("pendle")["convert_api"].format(chain_id=ctx.chain_id)
    amount = int(size_tokens * 10 ** ctx.token_meta(sell).decimals)
    params = {
        "receiver": ctx.registry.raw["aggregator"]["quote_receiver"],
        "slippage": "0.01",
        "enableAggregator": "true",
        "tokensIn": sell,
        "tokensOut": buy,
        "amountsIn": str(amount),
    }
    try:
        body = ctx.http.get(url, params=params, slim=_slim_convert)
        route = body["routes"][0]
        out = Decimal(route["outputs"][0]["amount"]) / 10 ** ctx.token_meta(buy).decimals
    except (SourceError, KeyError, IndexError, TypeError) as exc:
        ctx.warnings.append(f"Pendle router quote {sell}->{buy} unavailable: {exc}")
        return None
    data = route.get("data") or {}
    gas = route.get("data", {}).get("gasUsed") or (route.get("tx") or {}).get("gas")
    exchanges = ["pendle-amm"] + ([data["aggregatorType"].lower()] if data.get("aggregatorType") else [])
    return Quote("pendle_router", url, out, exchanges, [], gas_units=int(gas) if gas else None)


def _aggregator_quote(ctx: Ctx, sell: str, buy: str, size_tokens: Decimal) -> Quote | None:
    agg = ctx.registry.raw["aggregator"]
    amount = int(size_tokens * 10 ** ctx.token_meta(sell).decimals)
    try:
        body = ctx.http.get(
            agg["routes_api"],
            params={"tokenIn": sell, "tokenOut": buy, "amountIn": str(amount)},
            headers={"x-client-id": agg["client_id"]},
            slim=_slim_routes,
        )
    except SourceError as exc:
        ctx.warnings.append(f"aggregator quote {sell}->{buy} unavailable: {exc}")
        return None
    s = (body.get("data") or {}).get("routeSummary")
    if not s or not s.get("amountOut"):
        ctx.warnings.append(f"aggregator returned no route for {sell}->{buy}: {body.get('message')}")
        return None
    hops = [hop for path in s.get("route") or [] for hop in path]
    return Quote(
        "aggregator",
        agg["routes_api"],
        Decimal(s["amountOut"]) / 10 ** ctx.token_meta(buy).decimals,
        sorted({h["exchange"] for h in hops if h.get("exchange")}),
        sorted({h["pool"] for h in hops if h.get("pool")}),
        gas_usd=float(s["gasUsd"]) if s.get("gasUsd") else None,
        in_usd=float(s["amountInUsd"]) if s.get("amountInUsd") else None,
        out_usd=float(s["amountOutUsd"]) if s.get("amountOutUsd") else None,
    )


def _gas_usd(ctx: Ctx, quote: Quote, prices: dict[str, float]) -> tuple[float | None, str]:
    if quote.gas_usd is not None:
        return quote.gas_usd, "observed"
    if quote.gas_units is None or "ETH" not in prices:
        return None, "assumed"
    try:
        gas_price = ctx.evm.gas_price()
    except SourceError:
        return None, "assumed"
    return quote.gas_units * gas_price / 1e18 * prices["ETH"], "derived"


# snapshot entries ------------------------------------------------------------------------
def _exits(ctx: Ctx, venue: str, legs: list[Leg], evidence) -> None:
    for leg in legs:
        ctx.graph.edge(f"position:{leg.position_id}", venue, "exits_via", "exit_liquidity", evidence, "inferred")


def _from_quote(
    ctx: Ctx,
    venue: str,
    sell_node: str,
    sell_sym: str,
    buy_sym: str,
    size_tokens: Decimal,
    quote: Quote,
    legs: list[Leg],
    prices: dict[str, float],
) -> dict:
    marked = sell_sym in prices and buy_sym in prices
    if marked:
        size_usd = float(size_tokens) * prices[sell_sym]
        out_usd = float(quote.out_tokens) * prices[buy_sym]
    else:
        size_usd, out_usd = quote.in_usd or 0.0, quote.out_usd or 0.0
        ctx.warnings.append(
            f"{venue}: no snapshot price for {sell_sym} or {buy_sym}; quote valued with the quoting "
            "service's own USD prices"
        )
    if size_usd <= 0:
        ctx.warnings.append(f"{venue}: quote could not be valued in USD; falling back")
        return None
    loss = size_usd - out_usd
    if loss > 0:
        depth = size_usd * size_usd / loss - size_usd
    else:
        depth = size_usd * NO_IMPACT_DEPTH_MULTIPLE
        ctx.warnings.append(
            f"{venue}: quote shows no loss against the snapshot mark at {size_usd:,.0f} USD; depth "
            f"capped at {NO_IMPACT_DEPTH_MULTIPLE:,}x the size"
        )
    gas_usd, gas_source = _gas_usd(ctx, quote, prices)
    ctx.graph.nodes[venue].attributes.update(
        {
            "resolution": quote.source,
            "quoted_size_usd": decimal_str(size_usd, 2),
            "quoted_out_usd": decimal_str(out_usd, 2),
            "quoted_loss_pct": decimal_str(loss / size_usd * 100, 4),
            "valued_at": "snapshot prices" if marked else "quoting service prices",
            "route_exchanges": quote.exchanges,
            "route_pools": quote.pools[:12],
        }
    )
    note = (
        f"selling {decimal_str(size_tokens, 2)} {sell_sym} (mark {size_usd:,.0f} USD) returns {out_usd:,.0f} USD "
        f"via {', '.join(quote.exchanges) or 'quoted route'}: {loss / size_usd:.3%} all-in loss"
    )
    method = "protocol_api" if quote.source == "pendle_router" else "third_party_api"
    call = "GET convert (joint size of the venue)" if quote.source == "pendle_router" else "GET routes (joint size)"
    ctx.graph.edge(
        venue,
        sell_node,
        "pools_asset",
        "exit_liquidity",
        ctx.api(quote.url, note, call=call, method=method),
        "verified",
    )
    _exits(
        ctx, venue, legs, ctx.api(quote.url, "the position's asset is sold through this quoted route", method=method)
    )
    return {
        "asset": sell_sym,
        "quote_method": "executable_quote",
        "effective_depth_usd": decimal_str(depth, 2),
        "fee_rate": "0",
        "gas_usd": decimal_str(gas_usd, 2) if gas_usd is not None else "40",
        "venue_address": quote.pools[0] if len(quote.pools) == 1 else None,
        "source_type": "derived",
        "field_sources": {"effective_depth_usd": "derived", "fee_rate": "derived", "gas_usd": gas_source},
    }


def _from_pendle_pool(ctx: Ctx, venue: str, sell_node: str, sell_sym: str, market: str, legs: list[Leg]) -> dict:
    liquidity = ctx.facts["pendle_markets"][market]["liquidity_usd"]
    ctx.graph.nodes[venue].attributes.update({"resolution": "pendle_pool_liquidity", "venue_address": market})
    evidence = ctx.api(
        f"{ctx.registry.protocol('pendle')['api']}/v2/{ctx.chain_id}/markets/{market}/data",
        f"Pendle AMM liquidity {liquidity:,.0f} USD used as depth (no executable quote)",
    )
    ctx.graph.edge(venue, sell_node, "pools_asset", "exit_liquidity", evidence, "verified")
    _exits(ctx, venue, legs, evidence)
    ctx.warnings.append(f"{venue}: Pendle pool liquidity used as constant-product depth; the Pendle curve differs")
    return {
        "asset": sell_sym,
        "quote_method": "pool_reserves",
        "effective_depth_usd": decimal_str(liquidity, 2),
        "fee_rate": "0",
        "gas_usd": "40",
        "venue_address": market,
        "source_type": "observed",
        "field_sources": {"gas_usd": "assumed", "fee_rate": "assumed"},
    }


def _assumed(
    ctx: Ctx, venue: str, venue_id: str, sell_node: str, sell_sym: str, legs: list[Leg], assumed: dict | None
) -> dict | None:
    evidence = ctx.doc("backend/discovery/assumptions.json", "no quote or pool found: team assumption")
    evidence.method, evidence.status = "fixture", "assumed"
    ctx.graph.nodes[venue].attributes["resolution"] = "assumed"
    ctx.graph.edge(venue, sell_node, "pools_asset", "exit_liquidity", evidence, "assumed")
    _exits(ctx, venue, legs, evidence)
    ctx.unresolve(venue, "exit depth not observed: assumed proxy depth used", "market_and_liquidity")
    if assumed is None:
        ctx.warnings.append(f"{venue_id}: no quote and no assumption: venue omitted from the snapshot")
        return None
    return {**assumed, "asset": sell_sym, "quote_method": "proxy", "source_type": "assumed"}
