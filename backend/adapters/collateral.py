"""Layer 5 scan: which lending markets accept this exact token as collateral?

Run for Pendle PTs (the challenge's example). Found markets become context nodes with a
`collateral_asset` edge market -> token: the market depends on the token, not the other way
round, so a plain holder's dependency paths are unchanged, while a reverse query from the
token ("who is hit if this PT reprices?") finds them. Negative results are recorded too.
"""

from __future__ import annotations

from backend.adapters.aave import AaveAdapter
from backend.adapters.base import Ctx, Entity
from backend.adapters.morpho import MorphoAdapter

MIN_COLLATERAL_USD = 10_000
MAX_MARKETS = 3


class CollateralScanAdapter:
    name = "collateral_scan"

    def __init__(self, morpho: MorphoAdapter, aave: AaveAdapter):
        self.morpho, self.aave = morpho, aave

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        return entity.kind == "collateral_scan"

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        token = entity.key
        node = ctx.asset(token)
        symbol = ctx.graph.nodes[node].label
        scan = {"token": token, "symbol": symbol, "morpho": [], "aave": []}
        follow: list[Entity] = []

        for m in self.morpho.markets_accepting(ctx, token):
            usd = (m.get("state") or {}).get("collateralAssetsUsd") or 0
            row = {
                "market_id": m["marketId"],
                "loan": m["loanAsset"]["symbol"],
                "lltv": int(m["lltv"]) / 1e18,
                "collateral_usd": round(usd, 2),
                "listed": m.get("listed"),
            }
            scan["morpho"].append(row)
            if usd >= MIN_COLLATERAL_USD and len(follow) < MAX_MARKETS:
                follow.append(Entity("morpho_market", m["marketId"].lower()))

        for provider in ctx.registry.protocol("aave")["pool_addresses_providers"].values():
            listing = self.aave.reserve_listing(ctx, provider, token)
            scan["aave"].append({"provider": provider, **listing})
            if listing["listed"]:
                ctx.warnings.append(
                    f"{symbol} is an Aave reserve in {listing['market']}: context market not expanded "
                    "(no position-specific debt asset)"
                )

        ctx.facts.setdefault("collateral_scan", {})[token] = scan
        ctx.graph.nodes[node].attributes["collateral_scan"] = {
            "morpho_markets": len(scan["morpho"]),
            "aave_listed": [a["market"] for a in scan["aave"] if a["listed"]],
            "aave_checked": [f"{a['market']} ({a['reserves_checked']} reserves)" for a in scan["aave"]],
        }
        return follow
