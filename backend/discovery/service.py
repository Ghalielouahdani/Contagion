"""Discovery service (owner: P1): portfolio.json -> dependency_graph.json + market_snapshot.json.

Modes:
- fixture: return the contract fixtures (unblocks P2/P3/P4, no network);
- live:    read Ethereum and protocol APIs now (optionally record a cassette);
- replay:  rerun the live pipeline from a recorded cassette, offline and deterministic.

Every on-chain read is pinned to one block (latest - CONFIRMATIONS), so the snapshot never
mixes states from distant blocks. API data (Pendle, Morpho, KyberSwap) is time-stamped.
"""

from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from backend.adapters import default_adapters, venues
from backend.adapters.base import Ctx, Entity, Registry, decimal_str
from backend.adapters.sources import Cassette, EvmClient, HttpJson, SourceError, utc_now
from backend.discovery.coverage import position_coverage
from backend.discovery.explorer import Explorer, Limits
from backend.discovery.graph import GraphBuilder
from backend.discovery.validation import consistency_errors, schema_errors

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "contracts" / "fixtures"
ASSUMPTIONS = Path(__file__).with_name("assumptions.json")
CONFIRMATIONS = 3
SCHEMA_VERSION = "1.0"
SUSDE_APY_DIVERGENCE = 0.01


class DiscoveryError(Exception):
    pass


def discover(
    portfolio: dict,
    mode: str = "fixture",
    *,
    cassette: Path | None = None,
    record: bool = False,
    graph_id: str | None = None,
    snapshot_id: str | None = None,
    fixture_set: str = "demo_ethena_01",
    limits: Limits | None = None,
    validate: bool = True,
) -> tuple[dict, dict]:
    """Public entry point used by the API (P4) and the CLI."""
    errors = schema_errors(portfolio, "portfolio.schema.json")
    if errors:
        raise DiscoveryError("invalid portfolio: " + "; ".join(errors[:5]))
    if mode == "fixture":
        return _fixture(portfolio, fixture_set)
    if mode not in ("live", "replay"):
        raise ValueError(f"mode must be fixture, live or replay, not {mode!r}")
    pid = portfolio["portfolio_id"]
    graph, snapshot = _Run(portfolio, mode, cassette, record, limits or Limits()).execute(
        graph_id or f"graph_{pid}", snapshot_id or f"snapshot_{pid}"
    )
    if validate:
        problems = (
            schema_errors(graph, "dependency_graph.schema.json")
            + schema_errors(snapshot, "market_snapshot.schema.json")
            + consistency_errors(portfolio, graph, snapshot)
        )
        if problems:
            raise DiscoveryError("discovery output failed validation: " + "; ".join(problems[:10]))
    return graph, snapshot


def _fixture(portfolio: dict, fixture_set: str) -> tuple[dict, dict]:
    folder = FIXTURES / fixture_set
    graph = json.loads((folder / "dependency_graph.json").read_text())
    snapshot = json.loads((folder / "market_snapshot.json").read_text())
    if graph["portfolio_id"] != portfolio["portfolio_id"]:
        raise DiscoveryError(
            f"fixture set {fixture_set} is for portfolio {graph['portfolio_id']}, " f"not {portfolio['portfolio_id']}"
        )
    return graph, snapshot


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class _Run:
    def __init__(self, portfolio: dict, mode: str, cassette: Path | None, record: bool, limits: Limits):
        self.portfolio, self.mode, self.cassette_path, self.record, self.limits = (
            portfolio,
            mode,
            cassette,
            record,
            limits,
        )
        self.positions = portfolio["positions"]
        self.held: dict[str, str] = {}  # position_id -> token address held (token / PT holdings)

    # pipeline ----------------------------------------------------------------------------
    def execute(self, graph_id: str, snapshot_id: str) -> tuple[dict, dict]:
        if self.mode == "replay":
            cassette = Cassette("replay", self.cassette_path)
        else:
            cassette = Cassette("live", self.cassette_path if self.record else None)
        evm, http = EvmClient(cassette), HttpJson(cassette)

        chains = {p["chain_id"] for p in self.positions}
        if len(chains) != 1:
            raise DiscoveryError(f"one chain per discovery run in v1, got {sorted(chains)}")
        chain_id = evm.chain_id()
        if chain_id != chains.pop():
            raise DiscoveryError(f"RPC serves chain {chain_id}, portfolio is on chain {self.positions[0]['chain_id']}")
        registry = Registry.load(chain_id)
        block = cassette.meta["block"] if self.mode == "replay" else evm.latest_block() - CONFIRMATIONS
        evm.pin(block)
        block_ts = evm.block_timestamp(block)
        observed_at = cassette.meta["observed_at"] if self.mode == "replay" else utc_now()

        g = GraphBuilder()
        ctx = Ctx(evm, http, registry, g, chain_id, block, observed_at)
        ctx.facts["block_timestamp"] = block_ts
        g.node(
            registry.chain_node,
            "chain",
            registry.raw["network"],
            chain_id=chain_id,
            block_number=block,
            block_timestamp=_iso(block_ts),
            check="eth_chainId matches the portfolio's chain_id",
        )

        explorer = Explorer(ctx, default_adapters(), self.limits)
        explorer.run(self._positions(ctx))
        self._link_positions(ctx)
        prices, rates = self._prices(ctx)
        exit_venues = self._venues(ctx, {k: float(v["value"]) for k, v in prices.items()})
        self._holding_yields(ctx)

        coverage = {p["position_id"]: position_coverage(g, p, ctx.unresolved) for p in self.positions}
        self._attribute_unresolved(ctx)
        nodes, edges = g.to_contract()
        warnings = _dedupe(
            [
                f"Positions are fictional (data_origin); markets, tokens, oracles and venues are real, read on chain "
                f"{chain_id} at block {block}.",
                "Protocol API data (Pendle, Morpho, KyberSwap) is read at observed_at, not at the pinned block.",
                *ctx.warnings,
                *(f"conflict: {c}" for c in g.conflicts),
            ]
        )
        as_of = _iso(block_ts)
        graph = {
            "schema_version": SCHEMA_VERSION,
            "graph_id": graph_id,
            "portfolio_id": self.portfolio["portfolio_id"],
            "as_of": as_of,
            "chain_id": chain_id,
            "block_number": block,
            "nodes": nodes,
            "edges": edges,
            "warnings": warnings,
            "coverage": coverage,
            "unresolved": ctx.unresolved,
            "discovery": {
                "mode": self.mode,
                "observed_at": observed_at,
                "rpc": "env:ETH_RPC_URL" if os.environ.get("ETH_RPC_URL") else list(evm.urls),
                "limits": vars(self.limits),
                "entities_explored": len(explorer.visited),
                "rpc_calls": evm.calls,
                "http_calls": http.calls,
                "adapters": [a.name for a in explorer.adapters],
                "trace": explorer.trace,
            },
        }
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "as_of": as_of,
            "chain_id": chain_id,
            "block_number": block,
            "prices_usd": prices,
            "exchange_rates": rates,
            "markets": {pid: m for pid, m in ctx.market_params.items() if pid in self._ids()},
            "yields": {pid: y for pid, y in ctx.yields.items() if pid in self._ids()},
            # sUSDe's own yield, earned also when it is posted as collateral (Morpho pays none on collateral).
            **({"asset_yields": {"sUSDe": ctx.facts["susde_apy_selected"]}} if ctx.facts.get("susde_apy_selected") else {}),
            "exit_venues": exit_venues,
            "warnings": [w for w in warnings if not w.startswith("conflict")],
        }
        if self.record:
            cassette.save(
                {
                    "block": block,
                    "observed_at": observed_at,
                    "chain_id": chain_id,
                    "portfolio_id": self.portfolio["portfolio_id"],
                    "recorded_by": "backend.discovery",
                }
            )
        return graph, snapshot

    def _ids(self) -> set[str]:
        return {p["position_id"] for p in self.positions}

    # positions ---------------------------------------------------------------------------
    def _positions(self, ctx: Ctx) -> list[Entity]:
        seeds = []
        for p in self.positions:
            pid, kind = p["position_id"], p["position_type"]
            node = ctx.graph.node(
                f"position:{pid}",
                "position",
                _label(p),
                protocol=p["protocol"],
                position_type=kind,
                market_id=p["market_id"],
                data_origin=p["data_origin"],
                **{
                    k: p[k]
                    for k in (
                        "asset_symbol",
                        "quantity",
                        "collateral_asset",
                        "collateral_quantity",
                        "debt_asset",
                        "debt_quantity",
                    )
                    if k in p
                },
            )
            market = (p["market_id"] or "").lower()
            if kind == "token_holding":
                token = ctx.registry.token(p["asset_symbol"])
                if token is None:
                    ctx.unresolve(node, f"{p['asset_symbol']} is not a registry token: give its market instead")
                    continue
                self.held[pid] = token["address"]
                seeds.append(Entity("token", token["address"]))
            elif kind == "pt_holding":
                ctx.position_markets[market] = pid
                seeds.append(Entity("pendle_market", market))
            elif kind == "collateralized_borrow" and p["protocol"] == "morpho":
                ctx.position_markets[market] = pid
                seeds.append(Entity("morpho_market", market))
            elif kind == "collateralized_borrow" and p["protocol"] == "aave":
                seeds.append(
                    Entity(
                        "aave_market",
                        market,
                        (("position_id", pid), ("collateral", p["collateral_asset"]), ("debt", p["debt_asset"])),
                    )
                )
            else:
                ctx.unresolve(node, f"no adapter for {p['protocol']} {kind} positions")
        return seeds

    def _link_positions(self, ctx: Ctx) -> None:
        g = ctx.graph
        for p in self.positions:
            pid, kind = p["position_id"], p["position_type"]
            node, market = f"position:{pid}", f"market:{pid}"
            fictional = f"fictional position {pid} (data_origin={p['data_origin']}); "
            if kind == "token_holding" and pid in self.held:
                asset = g.node_for_address(ctx.chain_id, self.held[pid])
                if asset:
                    g.edge(
                        node,
                        asset,
                        "holds",
                        "mark_to_market",
                        ctx.onchain(
                            None,
                            fictional + f"holds {p['quantity']} {p['asset_symbol']}; token identity "
                            "verified on-chain",
                            call="symbol()/decimals()",
                            reference=self.held[pid],
                        ),
                        "verified",
                    )
                continue
            if market not in g.nodes:
                ctx.unresolve(node, f"market {p['market_id']} could not be discovered", "market_and_liquidity")
                continue
            ref = (
                g.nodes[market].attributes.get("address")
                or g.nodes[market].attributes.get("market_id")
                or p["market_id"]
            )
            channel = {"pt_holding": "maturity_redemption"}.get(kind, "collateral_liquidation")
            g.edge(
                node,
                market,
                "position_in",
                channel,
                ctx.onchain(
                    None, fictional + "its market_id resolves on-chain to this market", call="market_id", reference=ref
                ),
                "verified",
            )
            if kind == "pt_holding":
                facts = ctx.facts["pendle_markets"][p["market_id"].lower()]
                self.held[pid] = facts["pt"]
                pt_node = g.node_for_address(ctx.chain_id, facts["pt"])
                if p["asset_symbol"] != facts["pt_symbol"]:
                    ctx.warnings.append(
                        f"{pid}: asset_symbol {p['asset_symbol']} but the market's PT is " f"{facts['pt_symbol']}"
                    )
                g.edge(
                    node,
                    pt_node,
                    "holds",
                    "mark_to_market",
                    ctx.onchain(
                        None,
                        fictional + f"holds {p['quantity']} {facts['pt_symbol']}",
                        call="readTokens()",
                        reference=facts["pt"],
                    ),
                    "verified",
                )
            else:
                self._check_borrow(ctx, p, market)

    @staticmethod
    def _check_borrow(ctx: Ctx, p: dict, market: str) -> None:
        g = ctx.graph
        sides = {
            e.relation: g.nodes[e.target].label
            for e in g.out_edges(market)
            if e.relation in ("collateral_asset", "debt_asset")
        }
        if sides.get("collateral_asset") != p["collateral_asset"] or sides.get("debt_asset") != p["debt_asset"]:
            ctx.warnings.append(
                f"{p['position_id']}: portfolio says {p['collateral_asset']}/{p['debt_asset']}, "
                f"market is {sides.get('collateral_asset')}/{sides.get('debt_asset')} (conflict)"
            )
        borrowed = g.nodes[market].attributes.get("total_borrow")
        if borrowed is not None and Decimal(p["debt_quantity"]) > Decimal(borrowed):
            ctx.warnings.append(
                f"{p['position_id']}: fictional debt {p['debt_quantity']} {p['debt_asset']} exceeds the "
                f"market's total borrow ({borrowed}); the position could not exist at this size"
            )

    # venues ------------------------------------------------------------------------------
    def _venues(self, ctx: Ctx, prices: dict[str, float]) -> dict:
        assumed = json.loads(ASSUMPTIONS.read_text())["exit_venues"]
        usdc = ctx.registry.token("USDC")["address"]
        legs: dict[str, list[venues.Leg]] = defaultdict(list)
        for p in self.positions:
            pid = p["position_id"]
            sell = self.held.get(pid) or self._side_address(ctx, f"market:{pid}", "collateral_asset")
            buy = self._side_address(ctx, f"market:{pid}", "debt_asset") or usdc
            if sell is None:
                ctx.unresolve(
                    f"position:{pid}", "asset to sell unknown: exit venue not resolved", "market_and_liquidity"
                )
                continue
            qty = Decimal(p.get("quantity") or p.get("collateral_quantity"))
            legs[p["exit_venue_id"]].append(venues.Leg(pid, sell, qty, buy))
        out = {}
        for venue_id, group in sorted(legs.items()):
            try:
                resolved = venues.resolve(ctx, venue_id, group, assumed.get(venue_id), prices)
            except (SourceError, ValueError, KeyError) as exc:
                ctx.warnings.append(f"{venue_id}: resolution failed ({exc})")
                resolved = None
            if resolved:
                out[venue_id] = {k: v for k, v in resolved.items() if v is not None or k == "venue_address"}
        return out

    @staticmethod
    def _side_address(ctx: Ctx, market: str, relation: str) -> str | None:
        if market not in ctx.graph.nodes:
            return None
        targets = [e.target for e in ctx.graph.out_edges(market) if e.relation == relation]
        return ctx.graph.nodes[targets[0]].attributes.get("address") if targets else None

    # prices and yields -------------------------------------------------------------------
    def _prices(self, ctx: Ctx) -> tuple[dict, dict]:
        prices, rates = {}, {}
        feeds = {
            k: v for k, v in ctx.registry.raw["reference_feeds"].items() if not k.startswith("_") and k != "source"
        }
        for symbol, feed in feeds.items():
            desc = ctx.evm.try_call(feed, "description()(string)")
            data = ctx.evm.try_call(feed, "latestRoundData()(uint80,int256,uint256,uint256,uint80)")
            decimals = ctx.evm.try_call(feed, "decimals()(uint8)")
            if not (desc and data and decimals) or desc.value.replace(" ", "") != f"{symbol}/USD":
                ctx.warnings.append(
                    f"reference feed {feed} for {symbol}: unexpected description "
                    f"{desc.value if desc else None!r}; price not used"
                )
                continue
            age = ctx.facts["block_timestamp"] - data.value[3]
            if age > 25 * 3600:
                ctx.warnings.append(f"{symbol}/USD feed last updated {age / 3600:.1f} h before the snapshot block")
            prices[symbol] = {"value": decimal_str(data.value[1] / 10**decimals.value, 8), "source_type": "observed"}
        rate = ctx.facts.get("exchange_rates", {}).get("sUSDe_USDe")
        usde = float(prices["USDe"]["value"]) if "USDe" in prices else None
        if rate is not None:
            rates["sUSDe_USDe"] = {"value": decimal_str(rate, 12), "source_type": "observed"}
            if usde is not None:
                prices["sUSDe"] = {"value": decimal_str(rate * usde, 8), "source_type": "derived"}
        usde_address = ctx.registry.token("USDe")["address"]
        for market in ctx.facts.get("pendle_markets", {}).values():
            sy = ctx.graph.node_for_address(ctx.chain_id, market["sy"])
            accounting = ctx.graph.nodes[sy].attributes.get("accounting_asset") if sy else None
            discount = (1 + market["implied_apy"]) ** (market["days"] / 365)
            if accounting == usde_address and usde is not None:
                prices[market["pt_symbol"]] = {"value": decimal_str(usde / discount, 8), "source_type": "derived"}
            elif market.get("asset_price_usd_api"):
                prices[market["pt_symbol"]] = {
                    "value": decimal_str(market["asset_price_usd_api"] / discount, 8),
                    "source_type": "derived",
                }
                ctx.warnings.append(
                    f"{market['pt_symbol']}: accounting asset {accounting} has no on-chain reference "
                    "feed; its USD price comes from the Pendle API (assetPriceUsd)"
                )
            else:
                ctx.warnings.append(
                    f"{market['pt_symbol']}: accounting asset {accounting} has no USD price; PT price not derived"
                )
        return prices, rates

    def _susde_apy(self, ctx: Ctx, susde: str) -> dict | None:
        """sUSDe APY from the Pendle API (observed), else the short on-chain window (derived); None if neither."""
        api = next(
            (
                m["underlying_apy_api"]
                for m in ctx.facts.get("pendle_markets", {}).values()
                if m["underlying_apy_api"] is not None and self._sy_wraps(ctx, m["sy"], susde)
            ),
            None,
        )
        onchain = ctx.facts.get("susde_apy_onchain")
        if api is not None and onchain is not None and abs(api - onchain) > SUSDE_APY_DIVERGENCE:
            ctx.warnings.append(f"sUSDe APY: Pendle API {api:.2%} vs on-chain {onchain:.2%} over a short window")
        if api is not None:
            return {"value": decimal_str(api, 6), "source_type": "observed"}
        if onchain is not None:
            return {"value": decimal_str(onchain, 6), "source_type": "derived"}
        return None

    def _holding_yields(self, ctx: Ctx) -> None:
        susde = ctx.registry.token("sUSDe")["address"]
        usde = ctx.registry.token("USDe")["address"]
        susde_apy = self._susde_apy(ctx, susde)
        if susde_apy:
            ctx.facts["susde_apy_selected"] = susde_apy
        for p in self.positions:
            pid = p["position_id"]
            if p["position_type"] != "token_holding" or pid not in self.held:
                continue
            if self.held[pid] == usde:
                ctx.yields[pid] = {"token_apy": "0", "source_type": "derived"}
                continue
            if self.held[pid] != susde:
                ctx.unresolve(f"position:{pid}", "token yield not observable without a protocol adapter")
                continue
            if susde_apy:
                ctx.yields[pid] = {"token_apy": susde_apy["value"], "source_type": susde_apy["source_type"]}
            else:
                ctx.unresolve(f"position:{pid}", "sUSDe APY unavailable from both sources")

    @staticmethod
    def _sy_wraps(ctx: Ctx, sy: str, token: str) -> bool:
        node = ctx.graph.node_for_address(ctx.chain_id, sy)
        return bool(node) and any(
            e.relation == "wraps" and ctx.graph.nodes[e.target].attributes.get("address") == token
            for e in ctx.graph.out_edges(node)
        )

    def _attribute_unresolved(self, ctx: Ctx) -> None:
        closures = {
            p["position_id"]: {f"position:{p['position_id']}"}
            | {e.target for e in ctx.graph.reachable_edges(f"position:{p['position_id']}")}
            for p in self.positions
        }
        for item in ctx.unresolved:
            owners = [pid for pid, nodes in closures.items() if item["subject"] in nodes]
            if len(owners) == 1:
                item["position_id"] = owners[0]


def _label(p: dict) -> str:
    if p["position_type"] == "collateralized_borrow":
        return f"{p['protocol'].capitalize()} {p['collateral_asset']}-collateral {p['debt_asset']} borrow"
    return f"{p['asset_symbol']} holding"


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def revalue_portfolio(portfolio: dict, snapshot: dict) -> tuple[dict, list[str]]:
    """Recompute USD values from the snapshot's market prices (quantities are the fictional input)."""
    out, warnings = copy.deepcopy(portfolio), []
    prices = {k: Decimal(v["value"]) for k, v in snapshot["prices_usd"].items()}
    cent = Decimal("0.01")

    def value(symbol: str, qty: str) -> Decimal | None:
        if symbol not in prices:
            warnings.append(f"no snapshot price for {symbol}: value left unchanged")
            return None
        return (Decimal(qty) * prices[symbol]).quantize(cent, ROUND_HALF_UP)

    totals = {"gross_value_usd": Decimal(0), "debt_value_usd": Decimal(0), "net_equity_usd": Decimal(0)}
    for p in out["positions"]:
        if p["position_type"] == "collateralized_borrow":
            gross, debt = (
                value(p["collateral_asset"], p["collateral_quantity"]),
                value(p["debt_asset"], p["debt_quantity"]),
            )
        else:
            gross, debt = value(p["asset_symbol"], p["quantity"]), Decimal(0)
        if gross is not None and debt is not None:
            p["gross_value_usd"], p["debt_value_usd"] = f"{gross:.2f}", f"{debt:.2f}"
            p["net_equity_usd"] = f"{gross - debt:.2f}"
        for key in totals:
            totals[key] += Decimal(p[key])
    out["totals"] = {k: f"{v:.2f}" for k, v in totals.items()}
    out["as_of"] = snapshot["as_of"]
    return out, warnings
