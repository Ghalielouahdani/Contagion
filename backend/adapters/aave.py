"""Aave v3 adapter: one collateral/debt pair in one Aave market (PoolAddressesProvider).

Everything is read from the market's own contracts at the pinned block: Pool, PoolDataProvider
and AaveOracle come from the provider; reserve configuration, eMode categories (v3.2+
bitmaps), interest rates, and the price source of each asset. The price sources are then
opened by the oracle module to find what they really read.

market_id format: "<PoolAddressesProvider address>" or "<address>#emode=<id>".
Without an explicit eMode, the eligible category with the highest liquidation threshold is
chosen and the choice is flagged as inferred.
"""

from __future__ import annotations

from backend.adapters import oracles
from backend.adapters.base import Ctx, Entity, decimal_str

RAY = 10**27
SECONDS_PER_YEAR = 365 * 24 * 3600
MAX_EMODE_ID = 255
EMODE_BATCH = 64  # one multicall per 64 category ids
RESERVE_DATA = (
    "getReserveData(address)(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint16,address,address,"
    "address,address,uint256,uint256,uint256)"
)
CONFIG = "getReserveConfigurationData(address)(uint256,uint256,uint256,uint256,uint256,bool,bool,bool,bool,bool)"
DP_RESERVE_DATA = (
    "getReserveData(address)(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,"
    "uint256,uint256,uint40)"
)


def parse_market_id(market_id: str) -> tuple[str, int | None]:
    provider, _, rest = market_id.partition("#")
    emode = int(rest.split("=", 1)[1]) if rest.startswith("emode=") else None
    return provider.lower(), emode


def ray_apr_to_apy(rate_ray: int) -> float:
    """Aave rates are per-year APRs in ray, compounded per second."""
    apr = rate_ray / RAY
    return (1 + apr / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1


class AaveAdapter:
    name = "aave"

    def accepts(self, entity: Entity, ctx: Ctx) -> bool:
        return entity.kind == "aave_market"

    def contracts(self, ctx: Ctx, provider: str) -> dict:
        cache = ctx.facts.setdefault("aave_contracts", {})
        if provider not in cache:
            pool = ctx.evm.call(provider, "getPool()(address)")
            cache[provider] = {
                "pool_call": pool,
                "pool": pool.value,
                "oracle": ctx.evm.call(provider, "getPriceOracle()(address)").value,
                "data_provider": ctx.evm.call(provider, "getPoolDataProvider()(address)").value,
                "market_name": ctx.evm.call(provider, "getMarketId()(string)").value,
                "reserves": list(ctx.evm.call(pool.value, "getReservesList()(address[])").value),
            }
        return cache[provider]

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]:
        provider, emode_hint = parse_market_id(entity.key)
        position_id = entity.get("position_id")
        c = self.contracts(ctx, provider)
        coll = self._resolve(ctx, entity.get("collateral"), c["reserves"], c["market_name"])
        debt = self._resolve(ctx, entity.get("debt"), c["reserves"], c["market_name"])
        if coll is None or debt is None:
            return []
        reserve = {a: self._reserve(ctx, c, a) for a in (coll, debt)}
        emode = self._choose_emode(ctx, c, reserve[coll]["id"], reserve[debt]["id"], emode_hint, position_id)
        base = reserve[coll]["config"]
        lt = (emode["lt"] if emode else base[2]) / 1e4
        lb = (emode["lb"] if emode else base[3]) / 1e4 - 1
        ltv = (emode["ltv"] if emode else base[1]) / 1e4
        if not emode and base[1] == 0:
            ctx.warnings.append(
                f"Aave {c['market_name']}: collateral has LTV 0 outside eMode: no new borrow is possible"
            )

        coll_node, debt_node = ctx.asset(coll), ctx.asset(debt)
        coll_sym, debt_sym = ctx.graph.nodes[coll_node].label, ctx.graph.nodes[debt_node].label
        node_id = (
            f"market:{position_id}"
            if position_id
            else ctx.graph.allocate_id(
                "market", f"aave_{coll_sym}_{debt_sym}", ctx.chain_id, f"{c['pool']}:{coll}:{debt}"
            )
        )
        label = f"Aave {c['market_name']}: {coll_sym} collateral / {debt_sym} debt" + (
            f" (eMode {emode['id']} {emode['label']})" if emode else ""
        )
        ctx.graph.node(
            node_id,
            "market",
            label,
            chain_id=ctx.chain_id,
            protocol="aave",
            pool=c["pool"],
            pool_addresses_provider=provider,
            market_name=c["market_name"],
            emode_category=emode["id"] if emode else None,
            ltv=decimal_str(ltv, 4),
            liquidation_threshold=decimal_str(lt, 4),
            liquidation_bonus=decimal_str(lb, 4),
            collateral_reserve=self._reserve_attrs(reserve[coll]),
            debt_reserve=self._reserve_attrs(reserve[debt]),
        )
        ctx.settle(node_id, c["pool"])
        cfg_note = (
            f"eMode {emode['id']} '{emode['label']}' lists {coll_sym} as collateral and {debt_sym} as "
            "borrowable (category bitmaps)"
            if emode
            else "reserve configuration"
        )
        ctx.graph.edge(
            node_id,
            coll_node,
            "collateral_asset",
            "mark_to_market",
            ctx.onchain(
                reserve[coll]["config_call"],
                f"{coll_sym} is an active reserve usable as collateral; " f"{cfg_note}; LT {lt:.2%}",
            ),
            "verified",
        )
        ctx.graph.edge(
            node_id,
            debt_node,
            "debt_asset",
            "debt_cost",
            ctx.onchain(
                reserve[debt]["config_call"],
                f"{debt_sym} borrowing enabled " f"(variable APY {reserve[debt]['borrow_apy']:.2%})",
            ),
            "verified",
        )
        ctx.graph.edge(
            node_id,
            ctx.protocol_node("aave"),
            "part_of_protocol",
            "smart_contract",
            ctx.onchain(
                c["pool_call"],
                f"pool of '{c['market_name']}' from its PoolAddressesProvider "
                f"({ctx.registry.protocol('aave')['source']})",
            ),
            "verified",
        )

        reports = {}
        for asset, relation, role in (
            (coll, "prices_collateral_with", "collateral"),
            (debt, "prices_debt_with", "debt"),
        ):
            source = ctx.evm.call(c["oracle"], "getSourceOfAsset(address)(address)", asset)
            report = oracles.safe_inspect(ctx, source.value)
            reports[role] = (report, source.value)
            if report:
                why = oracles.usde_pass_through(report).explanation
                ctx.graph.edge(
                    node_id,
                    report.node_id,
                    relation,
                    "oracle_repricing",
                    ctx.onchain(
                        source, f"AaveOracle price source of the {role} asset, used for the health " f"factor; {why}"
                    ),
                    "verified",
                )
        if position_id:
            self._snapshot(ctx, position_id, c, emode, lt, lb, ltv, reserve, coll, debt, reports)
        return [Entity("token", coll), Entity("token", debt)]

    # reserves ----------------------------------------------------------------------------
    def _resolve(self, ctx: Ctx, symbol: str | None, reserves: list[str], market: str) -> str | None:
        token = ctx.registry.token(symbol) if symbol else None
        if token and token["address"] in reserves:
            return token["address"]
        matches = [a for a in reserves if ctx.token_meta(a).symbol == symbol]
        if len(matches) == 1:
            ctx.warnings.append(f"Aave {market}: {symbol} resolved by on-chain symbol only ({matches[0]})")
            return matches[0]
        ctx.unresolve(
            f"aave:{symbol}",
            f"{symbol} is not a reserve of {market} ({len(matches)} symbol matches)",
            "lending_collateral_market",
        )
        return None

    def _reserve(self, ctx: Ctx, c: dict, asset: str) -> dict:
        config = ctx.evm.call(c["data_provider"], CONFIG, asset)
        data = ctx.evm.call(c["data_provider"], DP_RESERVE_DATA, asset).values
        caps = ctx.evm.try_call(c["data_provider"], "getReserveCaps(address)(uint256,uint256)", asset)
        paused = ctx.evm.try_call(c["data_provider"], "getPaused(address)(bool)", asset)
        legacy = ctx.evm.call(c["pool"], RESERVE_DATA, asset).values
        if not config.values[8] or config.values[9]:
            ctx.warnings.append(f"Aave reserve {asset}: active={config.values[8]} frozen={config.values[9]}")
        return {
            "address": asset,
            "config": config.values,
            "config_call": config,
            "id": legacy[7],
            "supply_apy": ray_apr_to_apy(data[5]),
            "borrow_apy": ray_apr_to_apy(data[6]),
            "caps": caps.values if caps else None,
            "paused": paused.value if paused else None,
        }

    @staticmethod
    def _reserve_attrs(r: dict) -> dict:
        cfg = r["config"]
        return {
            "address": r["address"],
            "reserve_id": r["id"],
            "base_ltv": decimal_str(cfg[1] / 1e4, 4),
            "base_lt": decimal_str(cfg[2] / 1e4, 4),
            "base_liquidation_bonus": decimal_str(cfg[3] / 1e4 - 1, 4),
            "collateral_enabled": cfg[5],
            "borrowing_enabled": cfg[6],
            "active": cfg[8],
            "frozen": cfg[9],
            "paused": r["paused"],
            "supply_cap": r["caps"][0] if r["caps"] else None,
            "borrow_cap": r["caps"][1] if r["caps"] else None,
            "supply_apy": decimal_str(r["supply_apy"], 6),
            "variable_borrow_apy": decimal_str(r["borrow_apy"], 6),
        }

    # eMode -------------------------------------------------------------------------------
    def emodes(self, ctx: Ctx, pool: str, coll_id: int) -> list[dict]:
        """eMode categories (v3.2+ bitmaps) that list this reserve as collateral, with their parameters."""
        cache = ctx.facts.setdefault("aave_emodes", {})
        if (pool, coll_id) in cache:
            return cache[(pool, coll_id)]
        candidates: list[int] = []
        for start in range(1, MAX_EMODE_ID + 1, EMODE_BATCH):
            ids = list(range(start, min(start + EMODE_BATCH, MAX_EMODE_ID + 1)))
            bitmaps = ctx.evm.multicall([(pool, "getEModeCategoryCollateralBitmap(uint8)(uint128)", (i,)) for i in ids])
            if all(b is None or not b.value for b in bitmaps):
                break  # past the last configured category
            candidates += [i for i, b in zip(ids, bitmaps) if b is not None and b.value >> coll_id & 1]
        calls = []
        for i in candidates:
            calls += [
                (pool, "getEModeCategoryBorrowableBitmap(uint8)(uint128)", (i,)),
                (pool, "getEModeCategoryCollateralConfig(uint8)(uint16,uint16,uint16)", (i,)),
                (pool, "getEModeCategoryLabel(uint8)(string)", (i,)),
            ]
        results = ctx.evm.multicall(calls) if calls else []
        found = []
        for k, i in enumerate(candidates):
            borrow, cfg, label = results[3 * k : 3 * k + 3]
            if cfg is None:
                continue
            found.append(
                {
                    "id": i,
                    "label": label.value if label else "",
                    "ltv": cfg.values[0],
                    "lt": cfg.values[1],
                    "lb": cfg.values[2],
                    "borrowable": borrow.value if borrow else 0,
                }
            )
        if not candidates and ctx.evm.try_call(pool, "getEModeCategoryCollateralBitmap(uint8)(uint128)", 1) is None:
            ctx.warnings.append(f"Aave pool {pool}: eMode bitmaps unreadable (pre-3.2 pool?): base config used")
        cache[(pool, coll_id)] = found
        return found

    def _choose_emode(
        self, ctx: Ctx, c: dict, coll_id: int, debt_id: int, hint: int | None, position_id: str | None
    ) -> dict | None:
        eligible = [e for e in self.emodes(ctx, c["pool"], coll_id) if e["borrowable"] >> debt_id & 1]
        if hint is not None:
            chosen = next((e for e in eligible if e["id"] == hint), None)
            if chosen is None:
                ctx.warnings.append(
                    f"{position_id}: requested eMode {hint} does not allow this collateral/debt pair; "
                    f"eligible: {[e['id'] for e in eligible]}"
                )
            return chosen
        if not eligible:
            return None
        chosen = max(eligible, key=lambda e: (e["lt"], -e["id"]))
        if len(eligible) > 1:
            ctx.warnings.append(
                f"{position_id}: eMode not specified; chose {chosen['id']} '{chosen['label']}' "
                f"(highest LT) among {[(e['id'], e['label']) for e in eligible]} (inferred)"
            )
        return chosen

    def reserve_listing(self, ctx: Ctx, provider: str, token: str) -> dict:
        c = self.contracts(ctx, provider)
        return {
            "market": c["market_name"],
            "pool": c["pool"],
            "listed": token in c["reserves"],
            "reserves_checked": len(c["reserves"]),
        }

    # snapshot ----------------------------------------------------------------------------
    @staticmethod
    def _snapshot(
        ctx: Ctx,
        position_id: str,
        c: dict,
        emode: dict | None,
        lt: float,
        lb: float,
        ltv: float,
        reserve: dict,
        coll: str,
        debt: str,
        reports: dict,
    ) -> None:
        report, source = reports["collateral"]
        passthrough = oracles.usde_pass_through(report) if report else None
        known = passthrough is not None and passthrough.value is not None
        debt_report = reports["debt"][0]
        ctx.market_params[position_id] = {
            "market_kind": "aave_v3_reserve",
            "liquidation_threshold": decimal_str(lt, 4),
            "liquidation_bonus": decimal_str(lb, 4),
            "oracle_pass_through": passthrough.value if known else "1",
            "oracle_type": passthrough.oracle_type if passthrough else "unknown",
            "oracle_address": source,
            "emode_category": emode["id"] if emode else None,
            "verified": known,
            "source_type": "observed",
            "field_sources": {"oracle_pass_through": "derived" if known else "assumed", "liquidation_bonus": "derived"},
            "details": {
                "pool": c["pool"],
                "market_name": c["market_name"],
                "ltv": decimal_str(ltv, 4),
                "emode_label": emode["label"] if emode else None,
                "oracle_explanation": passthrough.explanation if passthrough else None,
                "debt_oracle_address": reports["debt"][1],
                "debt_oracle_type": oracles.usde_pass_through(debt_report).oracle_type if debt_report else None,
            },
            **({} if known else {"warnings": ["collateral oracle not fully classified: pass-through 1 assumed"]}),
        }
        ctx.yields[position_id] = {
            "collateral_supply_apy": decimal_str(reserve[coll]["supply_apy"], 6),
            "debt_borrow_apy": decimal_str(reserve[debt]["borrow_apy"], 6),
            "source_type": "derived",
        }
