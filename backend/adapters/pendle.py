"""Pendle adapter: PT market and AMM state, PT -> SY -> yield-bearing token.

Primary source: the market, PT and SY contracts (readTokens, readState, SY(), yieldToken()...).
Second source: the Pendle API (market list and market data), used to cross-check identities
and implied APY and to read pool liquidity in USD. Disagreements become warnings.
Pendle is never assumed to be the yield source: the SY's yieldToken is followed instead.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.adapters.base import Ctx, Entity, decimal_str
from backend.adapters.sources import SourceError

IMPLIED_APY_TOLERANCE = 0.0025  # absolute; API and chain are read a few seconds/blocks apart


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _slim_active(body: dict) -> dict:
    keep = ("name", "address", "expiry", "pt", "yt", "sy", "underlyingAsset")
    return {"markets": [{k: m.get(k) for k in keep} for m in body.get("markets", [])]}


class PendleAdapter:
    name = "pendle"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        if entity.kind == "pendle_market":
            return True
        return entity.kind == "token" and (self._is_pt(ctx, entity.key) or self._is_sy(ctx, entity.key))

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        if entity.kind == "pendle_market":
            return self._market(ctx, entity.key)
        if self._is_pt(ctx, entity.key):
            return self._pt(ctx, entity.key)
        return self._sy(ctx, entity.key)

    # classification ----------------------------------------------------------------------
    @staticmethod
    def _is_pt(ctx: Ctx, a: str) -> bool:
        return all(ctx.evm.try_call(a, s) for s in ("SY()(address)", "YT()(address)", "expiry()(uint256)"))

    @staticmethod
    def _is_sy(ctx: Ctx, a: str) -> bool:
        return all(
            ctx.evm.try_call(a, s)
            for s in ("yieldToken()(address)", "exchangeRate()(uint256)", "getTokensOut()(address[])")
        )

    # API ---------------------------------------------------------------------------------
    def _api(self, ctx: Ctx) -> str:
        return ctx.registry.protocol("pendle")["api"]

    def _active(self, ctx: Ctx) -> list[dict]:
        if "pendle_active" not in ctx.facts:
            try:
                ctx.facts["pendle_active"] = ctx.http.get(
                    f"{self._api(ctx)}/v1/{ctx.chain_id}/markets/active", slim=_slim_active
                )["markets"]
            except SourceError as exc:
                ctx.warnings.append(f"Pendle API market list unavailable: {exc}")
                ctx.facts["pendle_active"] = []
        return ctx.facts["pendle_active"]

    def _listed(self, ctx: Ctx, field: str, address: str) -> list[dict]:
        tag = f"{ctx.chain_id}-{address}"
        return [m for m in self._active(ctx) if m.get(field) in (tag, address)]

    # market ------------------------------------------------------------------------------
    def _market(self, ctx: Ctx, address: str) -> list[Entity]:
        tokens = ctx.evm.call(address, "readTokens()(address,address,address)")
        sy, pt, yt = tokens.values
        expiry = ctx.evm.call(address, "expiry()(uint256)").value
        expired = ctx.evm.try_call(address, "isExpired()(bool)")
        router = ctx.registry.protocol("pendle")["router"]
        state = ctx.evm.try_call(
            address,
            "readState(address)(int256,int256,int256,address,int256,uint256,uint256,uint256,uint256)",
            router,
        )
        if state:
            total_pt, total_sy, total_lp, _, scalar_root, _, ln_fee_root, reserve_fee, ln_implied = state.values
        else:
            storage = ctx.evm.call(address, "_storage()(int128,int128,uint96,uint16,uint16,uint16)")
            total_pt, total_sy, ln_implied = storage.values[0], storage.values[1], storage.values[2]
            total_lp = scalar_root = ln_fee_root = reserve_fee = None
        implied_apy = math.exp(ln_implied / 1e18) - 1
        now = ctx.facts.get("block_timestamp") or 0
        days = max(expiry - now, 0) / 86400

        listed = self._listed(ctx, "address", address)
        api_data = None
        try:
            api_data = ctx.http.get(f"{self._api(ctx)}/v2/{ctx.chain_id}/markets/{address}/data")
        except SourceError as exc:
            ctx.warnings.append(f"Pendle API market data unavailable for {address}: {exc}")
        self._cross_check(ctx, address, listed, api_data, pt, sy, yt, expiry, implied_apy)

        pt_node, sy_node = ctx.asset(pt), ctx.asset(sy)
        pt_symbol = ctx.graph.nodes[pt_node].label
        position_id = ctx.position_markets.get(address)
        node_id = (
            f"market:{position_id}"
            if position_id
            else ctx.graph.allocate_id("market", f"pendle_{address[2:10]}", ctx.chain_id, address)
        )
        amm = {
            "total_pt": str(total_pt),
            "total_sy": str(total_sy),
            "total_lp": str(total_lp),
            "scalar_root": str(scalar_root),
            "ln_fee_rate_root": str(ln_fee_root),
            "reserve_fee_percent": reserve_fee,
            "last_ln_implied_rate": str(ln_implied),
        }
        ctx.graph.node(
            node_id,
            "market",
            f"Pendle {pt_symbol} market (AMM)",
            address=address,
            chain_id=ctx.chain_id,
            protocol="pendle",
            expiry=_iso(expiry),
            is_expired=expired.value if expired else None,
            implied_apy=decimal_str(implied_apy, 6),
            amm=amm,
            yt=yt,
            liquidity_usd=decimal_str(api_data["liquidity"]["usd"], 2) if api_data else None,
            api_implied_apy=decimal_str(api_data["impliedApy"], 6) if api_data else None,
            api_timestamp=api_data.get("timestamp") if api_data else None,
        )
        ctx.graph.bind_address(node_id, ctx.chain_id, address)
        ctx.settle(node_id, address)
        for asset_node, label in ((pt_node, "PT"), (sy_node, "SY")):
            ctx.graph.edge(
                node_id,
                asset_node,
                "pools_asset",
                "exit_liquidity",
                ctx.onchain(
                    tokens,
                    f"AMM pool trades {label} against {'SY' if label == 'PT' else 'PT'}; "
                    f"reserves {amm['total_pt' if label == 'PT' else 'total_sy']} (wei)",
                ),
                "verified",
            )
        pendle = ctx.protocol_node("pendle")
        if listed:
            ctx.graph.edge(
                node_id,
                pendle,
                "part_of_protocol",
                "smart_contract",
                ctx.api(
                    f"{self._api(ctx)}/v1/{ctx.chain_id}/markets/active",
                    "market listed by the Pendle API with the same PT/SY/YT as on-chain readTokens()",
                ),
                "verified",
            )
        else:
            ctx.graph.edge(
                node_id,
                pendle,
                "part_of_protocol",
                "smart_contract",
                ctx.onchain(
                    tokens,
                    "implements Pendle's market interface; not in the API's active list (expired or unlisted)",
                    status="to_verify",
                ),
                "inferred",
            )

        ctx.facts.setdefault("pendle_markets", {})[address] = {
            "pt": pt,
            "sy": sy,
            "yt": yt,
            "expiry": expiry,
            "implied_apy": implied_apy,
            "days": days,
            "liquidity_usd": api_data["liquidity"]["usd"] if api_data else None,
            "underlying_apy_api": api_data.get("underlyingApy") if api_data else None,
            "pt_discount_api": api_data.get("ptDiscount") if api_data else None,
            "asset_price_usd_api": api_data.get("assetPriceUsd") if api_data else None,
            "node": node_id,
            "pt_symbol": pt_symbol,
        }
        ctx.facts.setdefault("pt_markets", {}).setdefault(pt, address)
        if position_id:
            ctx.market_params[position_id] = {
                "market_kind": "pendle_pt_market",
                "maturity": _iso(expiry),
                "days_to_maturity": decimal_str(days, 4),
                "pt_implied_apy": decimal_str(implied_apy, 6),
                "valuation_method": "implied_apy_discount",
                "market_address": address,
                "verified": True,
                "source_type": "observed",
                "field_sources": {"days_to_maturity": "derived", "pt_implied_apy": "derived"},
                "details": {
                    "pt": pt,
                    "sy": sy,
                    "yt": yt,
                    "last_ln_implied_rate": str(ln_implied),
                    "amm": amm,
                    "api_implied_apy": api_data.get("impliedApy") if api_data else None,
                    "liquidity_usd": api_data["liquidity"]["usd"] if api_data else None,
                    "note": "pt_implied_apy = exp(lastLnImpliedRate) - 1 read on-chain at the pinned block",
                },
            }
            ctx.yields[position_id] = {"token_apy": decimal_str(implied_apy, 6), "source_type": "derived"}
        return [Entity("token", pt), Entity("token", sy)]

    def _cross_check(
        self,
        ctx: Ctx,
        address: str,
        listed: list[dict],
        api_data: dict | None,
        pt: str,
        sy: str,
        yt: str,
        expiry: int,
        implied_apy: float,
    ) -> None:
        if listed:
            m = listed[0]
            for field, onchain in (("pt", pt), ("sy", sy), ("yt", yt)):
                if m.get(field, "").split("-")[-1].lower() != onchain:
                    ctx.warnings.append(
                        f"Pendle {address}: API {field}={m.get(field)} vs on-chain {onchain} (conflict)"
                    )
            api_expiry = int(datetime.fromisoformat(m["expiry"].replace("Z", "+00:00")).timestamp())
            if api_expiry != expiry:
                ctx.warnings.append(f"Pendle {address}: API expiry {m['expiry']} vs on-chain {_iso(expiry)} (conflict)")
        if api_data and abs(api_data["impliedApy"] - implied_apy) > IMPLIED_APY_TOLERANCE:
            ctx.warnings.append(
                f"Pendle {address}: implied APY on-chain {implied_apy:.4%} vs API "
                f"{api_data['impliedApy']:.4%} (beyond {IMPLIED_APY_TOLERANCE:.2%} tolerance)"
            )

    # tokens ------------------------------------------------------------------------------
    def _pt(self, ctx: Ctx, pt: str) -> list[Entity]:
        sy = ctx.evm.call(pt, "SY()(address)")
        yt = ctx.evm.call(pt, "YT()(address)").value
        expiry = ctx.evm.call(pt, "expiry()(uint256)").value
        pt_node, sy_node = ctx.asset(pt), ctx.asset(sy.value)
        ctx.graph.nodes[pt_node].attributes.update({"expiry": _iso(expiry), "yt": yt, "pendle_role": "PT"})
        ctx.graph.edge(
            pt_node,
            sy_node,
            "redeemable_for",
            "maturity_redemption",
            ctx.onchain(
                sy,
                f"at expiry ({_iso(expiry)}) 1 PT redeems for SY worth 1 unit of the SY's "
                "accounting asset; before expiry it only exits through the AMM",
            ),
            "verified",
        )
        markets = self._listed(ctx, "pt", pt)
        pendle = ctx.protocol_node("pendle")
        if markets:
            ctx.graph.edge(
                pt_node,
                pendle,
                "issued_by",
                "smart_contract",
                ctx.api(
                    f"{self._api(ctx)}/v1/{ctx.chain_id}/markets/active",
                    f"Pendle API lists this PT in market {markets[0]['address']}",
                ),
                "verified",
            )
        else:
            ctx.graph.edge(
                pt_node,
                pendle,
                "issued_by",
                "smart_contract",
                ctx.onchain(
                    sy, "implements Pendle's PT interface (SY/YT/expiry); not in the API list", status="to_verify"
                ),
                "inferred",
            )
        follow = [Entity("token", sy.value), Entity("collateral_scan", pt)]
        follow += [Entity("pendle_market", m["address"].lower()) for m in markets]
        return follow

    def _sy(self, ctx: Ctx, sy: str) -> list[Entity]:
        yield_token = ctx.evm.call(sy, "yieldToken()(address)")
        rate = ctx.evm.call(sy, "exchangeRate()(uint256)").value
        info = ctx.evm.try_call(sy, "assetInfo()(uint8,address,uint8)")
        tokens_in = ctx.evm.try_call(sy, "getTokensIn()(address[])")
        tokens_out = ctx.evm.try_call(sy, "getTokensOut()(address[])")
        sy_node, y_node = ctx.asset(sy), ctx.asset(yield_token.value)
        accounting = info.values[1] if info else None
        ctx.graph.nodes[sy_node].attributes.update(
            {
                "pendle_role": "SY",
                "exchange_rate": str(rate),
                "accounting_asset": accounting,
                "tokens_in": list(tokens_in.value) if tokens_in else None,
                "tokens_out": list(tokens_out.value) if tokens_out else None,
            }
        )
        ctx.graph.edge(
            sy_node,
            y_node,
            "wraps",
            "exchange_rate",
            ctx.onchain(
                yield_token,
                f"SY is a 1:1 wrapper of its yield token; exchangeRate() = {rate / 1e18:.6f}"
                " accounting-asset units per SY: the yield comes from this token, "
                "not from Pendle",
            ),
            "verified",
        )
        pendle = ctx.protocol_node("pendle")
        listed = self._listed(ctx, "sy", sy)
        ctx.graph.edge(
            sy_node,
            pendle,
            "issued_by",
            "smart_contract",
            ctx.api(f"{self._api(ctx)}/v1/{ctx.chain_id}/markets/active", "SY listed by the Pendle API")
            if listed
            else ctx.onchain(yield_token, "implements Pendle's SY interface", status="to_verify"),
            "verified" if listed else "inferred",
        )
        return [Entity("token", yield_token.value)]
