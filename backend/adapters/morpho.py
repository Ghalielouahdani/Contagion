"""Morpho Blue adapter: one isolated market (collateral, loan, oracle, IRM, LLTV).

Primary source: the Morpho Blue singleton (idToMarketParams, market) and the market's IRM
(borrowRateView), all at the pinned block. Second source: the Morpho API, used to
cross-check the parameters, read USD sizes, and find markets accepting a given collateral.
"""

from __future__ import annotations

import json
import math

from backend.adapters import oracles
from backend.adapters.base import ZERO_ADDRESS, Ctx, Entity, decimal_str
from backend.adapters.sources import SourceError

SECONDS_PER_YEAR = 365 * 24 * 3600
MAX_LIF, LIF_CURSOR = 1.15, 0.3  # Morpho Blue liquidation incentive constants (ConstantsLib)
STATE_FIELDS = "state { borrowApy supplyApy supplyAssetsUsd borrowAssetsUsd collateralAssetsUsd timestamp }"


def liquidation_incentive(lltv: float) -> float:
    """Morpho Blue: LIF = min(MAX_LIF, 1 / (1 - cursor * (1 - LLTV))); incentive = LIF - 1."""
    return min(MAX_LIF, 1 / (1 - LIF_CURSOR * (1 - lltv))) - 1


class MorphoAdapter:
    name = "morpho"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        return entity.kind == "morpho_market"

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        cfg = ctx.registry.protocol("morpho")
        blue, mid = cfg["morpho_blue"], entity.key
        raw_id = bytes.fromhex(mid[2:])
        params = ctx.evm.call(blue, "idToMarketParams(bytes32)(address,address,address,address,uint256)", raw_id)
        loan, collateral, oracle, irm, lltv_raw = params.values
        if loan == ZERO_ADDRESS:
            ctx.unresolve(
                f"morpho market {mid}", "id not created on Morpho Blue at the pinned block", "lending_collateral_market"
            )
            return []
        state = ctx.evm.call(blue, "market(bytes32)(uint128,uint128,uint128,uint128,uint128,uint128)", raw_id)
        supply_assets, _, borrow_assets, _, last_update, fee = state.values
        lltv = lltv_raw / 1e18
        borrow_apy = self._borrow_apy(ctx, params, state)
        api = self._api_market(ctx, mid)
        self._cross_check(ctx, mid, api, params)

        loan_node, coll_node = ctx.asset(loan), ctx.asset(collateral)
        loan_meta = ctx.token_meta(loan)
        position_id = ctx.position_markets.get(mid)
        node_id = (
            f"market:{position_id}"
            if position_id
            else ctx.graph.allocate_id("market", f"morpho_{mid[2:10]}", ctx.chain_id, mid)
        )
        label = (
            f"Morpho {ctx.graph.nodes[coll_node].label}/{ctx.graph.nodes[loan_node].label} market " f"(LLTV {lltv:.1%})"
        )
        api_state = (api or {}).get("state") or {}
        ctx.graph.node(
            node_id,
            "market",
            label,
            market_id=mid,
            chain_id=ctx.chain_id,
            protocol="morpho",
            lltv=decimal_str(lltv, 6),
            oracle=oracle,
            irm=irm,
            total_supply=decimal_str(supply_assets / 10**loan_meta.decimals, 2),
            total_borrow=decimal_str(borrow_assets / 10**loan_meta.decimals, 2),
            utilization=decimal_str(borrow_assets / supply_assets, 4) if supply_assets else None,
            borrow_apy=decimal_str(borrow_apy, 6) if borrow_apy is not None else None,
            collateral_usd=decimal_str(api_state["collateralAssetsUsd"], 2)
            if api_state.get("collateralAssetsUsd") is not None
            else None,
            listed=(api or {}).get("listed"),
            context_only=position_id is None,
        )
        ctx.graph.bind_address(node_id, ctx.chain_id, mid)
        ctx.settle(node_id, blue)
        call = "idToMarketParams(bytes32)"
        ctx.graph.edge(
            node_id,
            coll_node,
            "collateral_asset",
            "mark_to_market",
            ctx.onchain(params, "MarketParams.collateralToken", call=call),
            "verified",
        )
        ctx.graph.edge(
            node_id,
            loan_node,
            "debt_asset",
            "debt_cost",
            ctx.onchain(params, f"MarketParams.loanToken; borrow rate from IRM {irm}", call=call),
            "verified",
        )
        ctx.graph.edge(
            node_id,
            ctx.protocol_node("morpho"),
            "part_of_protocol",
            "smart_contract",
            ctx.onchain(params, f"market lives in the Morpho Blue singleton listed at {cfg['source']}", call=call),
            "verified",
        )

        report = oracles.safe_inspect(ctx, oracle)
        passthrough = oracles.usde_pass_through(report) if report else None
        if report:
            ctx.graph.edge(
                node_id,
                report.node_id,
                "prices_collateral_with",
                "oracle_repricing",
                ctx.onchain(
                    params,
                    "MarketParams.oracle: the only price used for LTV and liquidations; " + passthrough.explanation,
                    call=call,
                ),
                "verified",
            )
        if position_id:
            self._snapshot(ctx, position_id, mid, params, lltv, borrow_apy, passthrough, api, oracle)
        return [Entity("token", collateral), Entity("token", loan)]

    # helpers -----------------------------------------------------------------------------
    @staticmethod
    def _borrow_apy(ctx: Ctx, params, state) -> float | None:
        irm = params.values[3]
        if irm == ZERO_ADDRESS:
            return 0.0
        rate = ctx.evm.try_call(
            irm,
            "borrowRateView((address,address,address,address,uint256),"
            "(uint128,uint128,uint128,uint128,uint128,uint128))(uint256)",
            params.values,
            state.values,
        )
        return math.exp(rate.value / 1e18 * SECONDS_PER_YEAR) - 1 if rate else None

    def _graphql(self, ctx: Ctx, query: str) -> dict | None:
        url = ctx.registry.protocol("morpho")["api"]
        try:
            body = ctx.http.post(url, {"query": query})
        except SourceError as exc:
            ctx.warnings.append(f"Morpho API unavailable: {exc}")
            return None
        if body.get("errors"):
            ctx.warnings.append(f"Morpho API error: {body['errors'][0].get('message')}")
            return None
        return body["data"]

    def _api_market(self, ctx: Ctx, mid: str) -> dict | None:
        q = (
            "{ markets(where: { uniqueKey_in: [%s], chainId_in: [%d] }) { items { marketId lltv listed "
            "oracle { address } loanAsset { address } collateralAsset { address } %s } } }"
            % (json.dumps(mid), ctx.chain_id, STATE_FIELDS)
        )
        data = self._graphql(ctx, q)
        items = (data or {}).get("markets", {}).get("items", [])
        return items[0] if items else None

    def markets_accepting(self, ctx: Ctx, collateral: str, limit: int = 5) -> list[dict]:
        q = (
            "{ markets(first: %d, orderBy: SupplyAssetsUsd, orderDirection: Desc, where: "
            "{ collateralAssetAddress_in: [%s], chainId_in: [%d] }) { items { marketId lltv listed "
            "oracle { address } loanAsset { address symbol } %s } } }"
            % (limit, json.dumps(collateral), ctx.chain_id, STATE_FIELDS)
        )
        data = self._graphql(ctx, q)
        return (data or {}).get("markets", {}).get("items", [])

    @staticmethod
    def _cross_check(ctx: Ctx, mid: str, api: dict | None, params) -> None:
        if api is None:
            ctx.warnings.append(f"Morpho market {mid}: no API record, on-chain values used alone")
            return
        loan, collateral, oracle, _, lltv_raw = params.values
        checks = {
            "lltv": (str(api["lltv"]), str(lltv_raw)),
            "oracle": ((api.get("oracle") or {}).get("address", "").lower(), oracle),
            "loan": (api["loanAsset"]["address"].lower(), loan),
            "collateral": (api["collateralAsset"]["address"].lower(), collateral),
        }
        for name, (from_api, onchain) in checks.items():
            if from_api != onchain:
                ctx.warnings.append(f"Morpho market {mid}: {name} API={from_api} vs on-chain={onchain} (conflict)")

    @staticmethod
    def _snapshot(
        ctx: Ctx,
        position_id: str,
        mid: str,
        params,
        lltv: float,
        borrow_apy: float | None,
        passthrough,
        api: dict | None,
        oracle: str,
    ) -> None:
        known = passthrough is not None and passthrough.value is not None
        warnings = (
            []
            if known
            else [
                "oracle could not be fully classified: pass-through 1.0 is a conservative "
                "assumption, not an observation"
            ]
        )
        api_state = (api or {}).get("state") or {}
        ctx.market_params[position_id] = {
            "market_kind": "morpho_blue_market",
            "lltv": decimal_str(lltv, 6),
            "liquidation_incentive": decimal_str(liquidation_incentive(lltv), 6),
            "oracle_pass_through": passthrough.value if known else "1",
            "oracle_type": passthrough.oracle_type if passthrough else "unknown",
            "oracle_address": oracle,
            "verified": known,
            "source_type": "observed",
            "field_sources": {
                "liquidation_incentive": "derived",
                "oracle_pass_through": "derived" if known else "assumed",
            },
            "details": {
                "market_id": mid,
                "loan_token": params.values[0],
                "collateral_token": params.values[1],
                "irm": params.values[3],
                "oracle_explanation": passthrough.explanation if passthrough else None,
                "oracle_backup_pass_through": passthrough.backup_value if passthrough else None,
                "api_borrow_apy": api_state.get("borrowApy"),
                "api_supply_usd": api_state.get("supplyAssetsUsd"),
                "api_borrow_usd": api_state.get("borrowAssetsUsd"),
            },
            **({"warnings": warnings} if warnings else {}),
        }
        borrow = borrow_apy if borrow_apy is not None else api_state.get("borrowApy")
        if borrow is not None:
            ctx.yields[position_id] = {
                "collateral_supply_apy": "0",
                "debt_borrow_apy": decimal_str(borrow, 6),
                "source_type": "observed",
                "field_sources": {
                    "collateral_supply_apy": "derived",
                    "debt_borrow_apy": "derived" if borrow_apy is not None else "observed",
                },
            }
