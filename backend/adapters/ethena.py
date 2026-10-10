"""Ethena adapter: USDe and sUSDe (issuer, staking vault, yield source, off-chain backing).

On-chain facts (verified): sUSDe.asset() == USDe, sUSDe exchange rate (convertToAssets),
cooldown, rewards currently vesting, USDe.minter() == the minting contract Ethena publishes.
Off-chain facts (documented only): custody, hedges and reserve fund backing USDe.
"""

from __future__ import annotations

import math

from backend.adapters.base import Ctx, Entity
from backend.adapters.sources import SourceError

SECONDS_PER_YEAR = 365 * 24 * 3600
APY_WINDOW_BLOCKS = 50  # short window: public RPCs only serve recent state without an archive key


class EthenaAdapter:
    name = "ethena"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        known = ctx.registry.token_by_address(entity.key) if entity.kind == "token" else None
        return bool(known and known[1]["issuer"] == "ethena")

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        symbol, _ = ctx.registry.token_by_address(entity.key)
        issuer = ctx.registry.issuer("ethena")
        ethena = ctx.graph.node(issuer["node"], "protocol", issuer["label"], docs=issuer["source"])
        node = ctx.asset(entity.key)
        if symbol == "USDe":
            return self._usde(ctx, node, entity.key, issuer, ethena)
        return self._staked(ctx, node, entity.key, issuer, ethena)

    def _usde(self, ctx: Ctx, node: str, address: str, issuer: dict, ethena: str) -> list[Entity]:
        minter = ctx.evm.try_call(address, "minter()(address)")
        supply = ctx.evm.try_call(address, "totalSupply()(uint256)")
        if supply:
            ctx.graph.nodes[node].attributes["total_supply"] = str(supply.value)
        documented = issuer["minting_contract"]
        if minter and minter.value == documented:
            minting = ctx.graph.node(
                f"contract:ethena_minting.{documented[2:10]}",
                "contract",
                "Ethena minting contract",
                address=documented,
                chain_id=ctx.chain_id,
            )
            ctx.graph.edge(
                minting,
                ethena,
                "part_of_protocol",
                "smart_contract",
                ctx.doc(issuer["minting_source"], "listed in Ethena's published key addresses"),
                "documented",
            )
            ctx.graph.edge(
                node,
                minting,
                "issued_by",
                "issuer_backing",
                ctx.onchain(
                    minter,
                    "USDe.minter() is the minting contract Ethena publishes: mint/redeem of USDe goes through it",
                ),
                "verified",
            )
            ctx.graph.edge(
                node,
                ethena,
                "issued_by",
                "issuer_backing",
                ctx.onchain(minter, f"on-chain minter matches {issuer['minting_source']}"),
                "verified",
            )
        else:
            found = minter.value if minter else "unreadable"
            ctx.warnings.append(f"USDe.minter() = {found}, documented minting contract is {documented}: conflict")
            ctx.graph.edge(
                node,
                ethena,
                "issued_by",
                "issuer_backing",
                ctx.doc(issuer["source"], "issuer per Ethena documentation (on-chain minter check failed)"),
                "documented",
            )
        backing = issuer["backing"]
        backing_node = ctx.graph.node(backing["node"], "offchain_entity", backing["label"], docs=backing["source"])
        ctx.graph.edge(
            node,
            backing_node,
            "backed_by",
            "custody",
            ctx.doc(
                backing["source"],
                "USDe is backed by off-chain custody, delta-hedging derivative "
                "positions and a reserve fund; not observable on-chain",
            ),
            "documented",
        )
        ctx.graph.edge(
            ethena,
            backing_node,
            "yield_generated_by",
            "yield_source",
            ctx.doc(
                backing["source"],
                "protocol revenue comes from the hedged backing (funding/basis and "
                "staking/reserve yield), per Ethena documentation",
            ),
            "documented",
        )
        return []

    def _staked(self, ctx: Ctx, node: str, address: str, issuer: dict, ethena: str) -> list[Entity]:
        asset = ctx.evm.call(address, "asset()(address)")
        usde = ctx.registry.token("USDe")["address"]
        if asset.value != usde:
            ctx.warnings.append(f"sUSDe.asset() = {asset.value}, registry USDe is {usde}: conflict")
        usde_node = ctx.asset(asset.value)
        one = 10 ** ctx.token_meta(address).decimals
        rate_now = ctx.evm.call(address, "convertToAssets(uint256)(uint256)", one)
        cooldown = ctx.evm.try_call(address, "cooldownDuration()(uint24)")
        vesting = ctx.evm.try_call(address, "vestingAmount()(uint256)")
        unvested = ctx.evm.try_call(address, "getUnvestedAmount()(uint256)")
        rate = rate_now.value / 10 ** ctx.token_meta(asset.value).decimals
        ctx.facts.setdefault("exchange_rates", {})["sUSDe_USDe"] = rate
        cooldown_s = cooldown.value if cooldown else None
        ctx.graph.nodes[node].attributes.update(
            {
                "exchange_rate_to_USDe": f"{rate:.12f}",
                "cooldown_seconds": cooldown_s,
                "rewards_vesting": str(vesting.value) if vesting else None,
            }
        )
        redemption = (
            "redemption needs a cooldown of " f"{cooldown_s / 3600:g} h: not an instant exit"
            if cooldown_s
            else "no cooldown reported"
        )
        ctx.graph.edge(
            node,
            usde_node,
            "redeemable_for",
            "exchange_rate",
            ctx.onchain(asset, f"ERC-4626 vault over USDe; 1 sUSDe = {rate:.6f} USDe; {redemption}"),
            "verified",
        )
        ctx.graph.edge(
            node,
            ethena,
            "issued_by",
            "smart_contract",
            ctx.doc(
                ctx.registry.token("sUSDe")["source"],
                "staking vault listed in Ethena key addresses; symbol/decimals verified on-chain",
            ),
            "documented",
        )
        if vesting and vesting.value > 0:
            ctx.graph.edge(
                node,
                ethena,
                "yield_generated_by",
                "yield_source",
                ctx.onchain(
                    vesting,
                    f"Ethena pushes protocol rewards into the vault; "
                    f"{vesting.value / 1e18:,.0f} USDe currently vesting"
                    + (f" ({unvested.value / 1e18:,.0f} still unvested)" if unvested else ""),
                ),
                "verified",
            )
        else:
            ctx.graph.edge(
                node,
                ethena,
                "yield_generated_by",
                "yield_source",
                ctx.doc(issuer["source"], "staking yield distributed by Ethena (no rewards vesting now)"),
                "documented",
            )
        apy = self._onchain_apy(ctx, address, one, rate_now.value)
        if apy is not None:
            ctx.facts["susde_apy_onchain"] = apy
        return [Entity("token", asset.value)]

    @staticmethod
    def _onchain_apy(ctx: Ctx, address: str, one: int, rate_now: int) -> float | None:
        """Annualised exchange-rate growth over the last APY_WINDOW_BLOCKS blocks (noisy: rewards vest in steps)."""
        if ctx.block is None:
            return None
        past = ctx.block - APY_WINDOW_BLOCKS
        try:
            rate_past = ctx.evm.call(address, "convertToAssets(uint256)(uint256)", one, block=past).value
            dt = ctx.evm.block_timestamp(ctx.block) - ctx.evm.block_timestamp(past)
        except SourceError as exc:  # archive limits on public RPCs
            ctx.warnings.append(f"sUSDe on-chain APY window unavailable: {exc}")
            return None
        if dt <= 0 or rate_past <= 0:
            return None
        return math.exp(math.log(rate_now / rate_past) * SECONDS_PER_YEAR / dt) - 1
