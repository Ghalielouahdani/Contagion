"""Generic token adapters, used when no protocol adapter claims a token.

- ERC-4626 vault: the redemption link to its underlying is verified on-chain (asset()),
  but who generates the yield stays unresolved unless a protocol adapter knows the vault.
- Plain ERC-20: the issuer comes from the registry (documented) or stays unresolved.
Nothing here guesses an issuer from a symbol.
"""

from __future__ import annotations

from backend.adapters.base import Ctx, Entity


class Erc4626Adapter:
    name = "erc4626"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        if entity.kind != "token":
            return False
        try:
            one = 10 ** ctx.token_meta(entity.key).decimals
        except ValueError:
            return False
        return bool(
            ctx.evm.try_call(entity.key, "asset()(address)")
            and ctx.evm.try_call(entity.key, "convertToAssets(uint256)(uint256)", one)
        )

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        vault = ctx.asset(entity.key)
        asset = ctx.evm.call(entity.key, "asset()(address)")
        one = 10 ** ctx.token_meta(entity.key).decimals
        assets = ctx.evm.call(entity.key, "convertToAssets(uint256)(uint256)", one).value
        underlying = ctx.asset(asset.value)
        rate = assets / 10 ** ctx.token_meta(asset.value).decimals
        ctx.graph.nodes[vault].attributes["exchange_rate_to_underlying"] = f"{rate:.12f}"
        ctx.graph.edge(
            vault,
            underlying,
            "redeemable_for",
            "exchange_rate",
            ctx.onchain(asset, f"ERC-4626 vault: 1 share = {rate:.6f} underlying"),
            "verified",
        )
        _registry_issuer(ctx, vault, entity.key)
        return [Entity("token", asset.value)]


class Erc20Adapter:
    name = "erc20"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        return entity.kind == "token"

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        node = ctx.asset(entity.key)
        _registry_issuer(ctx, node, entity.key)
        return []


def _registry_issuer(ctx: Ctx, node: str, address: str) -> None:
    known = ctx.registry.token_by_address(address)
    if not known:
        ctx.unresolve(
            node,
            f"issuer and yield source of {ctx.graph.nodes[node].label} not identified: no protocol "
            "adapter or registry entry for this contract",
            "yield_source_and_issuer",
        )
        return
    symbol, entry = known
    issuer = ctx.registry.issuer(entry["issuer"])
    issuer_node = ctx.graph.node(
        issuer["node"], issuer.get("type", "offchain_entity"), issuer["label"], docs=issuer["source"]
    )
    ctx.graph.edge(
        node,
        issuer_node,
        "issued_by",
        "issuer_backing",
        ctx.doc(
            entry["source"],
            f"{symbol} contract published by its issuer; symbol/decimals verified on-chain; reserves are off-chain",
        ),
        "documented",
    )
