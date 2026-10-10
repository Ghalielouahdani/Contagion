"""Oracle introspection: which price inputs does a protocol's oracle actually read?

The oracle a market consumes is identified by the market itself (Aave getSourceOfAsset,
Morpho MarketParams.oracle). This module then opens it recursively, by probing the getters
each known oracle family exposes, and records every component as a node:

  meta_oracle            primaryOracle/backupOracle/currentOracle (primary with challengeable backup)
  morpho_chainlink_v2    BASE_VAULT, BASE_FEED_1/2, QUOTE_VAULT, QUOTE_FEED_1/2, SCALE_FACTOR
  aave_ratio_adapter     RATIO_PROVIDER x BASE_TO_USD_AGGREGATOR (e.g. sUSDe rate x USDT/USD)
  aave_capped_feed       ASSET_TO_USD_AGGREGATOR with a price cap
  pendle_linear_discount PT, baseDiscountPerYear, maturity (deterministic, no market input)
  chainlink_feed         description + latestRoundData ("USDe / USD")
  constant_feed          feed whose description says it is a dummy/constant

From the drivers it derives the USDe pass-through the risk engine needs: 1 if the active
oracle path reads a USDe (or sUSDe) market feed, 0 if it only reads exchange rates, a
deterministic discount or other assets' feeds. An unclassified component makes it unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.adapters.base import ZERO_ADDRESS, Ctx
from backend.adapters.sources import CallReverted
from backend.discovery.graph import safe_name

EIP1167_PREFIX = "0x363d3d373d3d3d363d73"
USDE_LIKE = {"USDe", "sUSDe"}
MAX_ORACLE_DEPTH = 4


@dataclass(frozen=True)
class Driver:
    kind: str  # feed | rate | linear_discount | constant | unknown
    detail: str  # "USDe/USD", "sUSDe", PT symbol...
    side: str = "base"  # base | quote (quote inputs divide the price)


@dataclass
class OracleReport:
    address: str
    node_id: str
    kind: str
    label: str
    drivers: list[Driver] = field(default_factory=list)  # inputs on the ACTIVE path
    alternates: list[Driver] = field(default_factory=list)  # inputs of an inactive backup
    facts: dict = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return all(d.kind != "unknown" for d in self.drivers)


def inspect(ctx: Ctx, address: str, depth: int = 0, side: str = "base") -> OracleReport:
    address = address.lower()
    cache = ctx.facts.setdefault("oracles", {})
    if address in cache:
        report = cache[address]
        return report if side == "base" else _flip(report)
    report = _inspect(ctx, address, depth)
    cache[address] = report
    return report if side == "base" else _flip(report)


def _flip(report: OracleReport) -> OracleReport:
    flipped = OracleReport(report.address, report.node_id, report.kind, report.label, facts=report.facts)
    flipped.drivers = [Driver(d.kind, d.detail, "quote" if d.side == "base" else "base") for d in report.drivers]
    flipped.alternates = [Driver(d.kind, d.detail, "quote" if d.side == "base" else "base") for d in report.alternates]
    return flipped


def _get(ctx: Ctx, address: str, signature: str):
    return ctx.evm.try_call(address, signature)


def _has(ctx: Ctx, address: str, *signatures: str) -> bool:
    return all(_get(ctx, address, s) is not None for s in signatures)


def _node(ctx: Ctx, address: str, slug: str, label: str, kind: str, **attrs) -> str:
    node_id = ctx.graph.allocate_id("oracle", f"{slug}.{address[2:10]}", ctx.chain_id, address)
    ctx.graph.node(node_id, "oracle", label, address=address, chain_id=ctx.chain_id, oracle_kind=kind, **attrs)
    ctx.graph.bind_address(node_id, ctx.chain_id, address)
    return node_id


def _proxy_impl(ctx: Ctx, address: str) -> str | None:
    code = ctx.evm.get_code(address)
    if code["size"] == 45 and code["head"].startswith(EIP1167_PREFIX):
        return "0x" + code["head"][22:62]
    return None


def _inspect(ctx: Ctx, a: str, depth: int) -> OracleReport:
    impl = _proxy_impl(ctx, a)
    extra = {"eip1167_implementation": impl} if impl else {}
    if depth > MAX_ORACLE_DEPTH:
        node_id = _node(ctx, a, "unexplored", f"Oracle {a[:10]} (not explored: depth limit)", "unexplored", **extra)
        ctx.unresolve(node_id, f"oracle nesting deeper than {MAX_ORACLE_DEPTH}", "oracle")
        return OracleReport(a, node_id, "unexplored", "unexplored", [Driver("unknown", a)])

    if _has(ctx, a, "primaryOracle()(address)", "backupOracle()(address)", "currentOracle()(address)"):
        return _meta(ctx, a, depth, extra)
    if _has(ctx, a, "BASE_FEED_1()(address)", "QUOTE_FEED_1()(address)", "SCALE_FACTOR()(uint256)"):
        return _morpho_v2(ctx, a, depth, extra)
    if _has(ctx, a, "RATIO_PROVIDER()(address)", "BASE_TO_USD_AGGREGATOR()(address)"):
        return _aave_ratio(ctx, a, depth, extra)
    if _has(ctx, a, "ASSET_TO_USD_AGGREGATOR()(address)"):
        return _aave_capped(ctx, a, depth, extra)
    if _has(ctx, a, "PT()(address)", "baseDiscountPerYear()(uint256)", "maturity()(uint256)"):
        return _pendle_discount(ctx, a, extra)
    if _has(ctx, a, "description()(string)", "latestRoundData()(uint80,int256,uint256,uint256,uint80)"):
        return _feed(ctx, a, extra)

    price = _get(ctx, a, "price()(uint256)") or _get(ctx, a, "latestAnswer()(int256)")
    node_id = _node(
        ctx,
        a,
        "unknown",
        f"Unclassified oracle {a[:10]}",
        "unknown",
        raw_price=str(price.value) if price else None,
        **extra,
    )
    ctx.unresolve(
        node_id, "oracle family not recognised: its price inputs (and USDe pass-through) are unknown", "oracle"
    )
    return OracleReport(a, node_id, "unknown", "unknown", [Driver("unknown", a)])


def _child(
    ctx: Ctx,
    parent: OracleReport,
    address: str,
    role: str,
    getter: str,
    depth: int,
    side: str = "base",
    note: str = "",
    confidence: str = "verified",
) -> OracleReport:
    child = inspect(ctx, address, depth + 1, side)
    ctx.graph.edge(
        parent.node_id,
        child.node_id,
        "uses_feed",
        "oracle_repricing",
        ctx.onchain(None, note or f"{role} component of the oracle", call=getter, reference=parent.address),
        confidence,
    )
    return child


def _meta(ctx: Ctx, a: str, depth: int, extra: dict) -> OracleReport:
    primary = _get(ctx, a, "primaryOracle()(address)").value
    backup = _get(ctx, a, "backupOracle()(address)").value
    current = _get(ctx, a, "currentOracle()(address)").value
    threshold = _get(ctx, a, "deviationThreshold()(uint256)")
    deviation = _get(ctx, a, "getDeviation()(uint256)")
    challenged = _get(ctx, a, "isChallenged()(bool)")
    timelock = _get(ctx, a, "challengeTimelockDuration()(uint256)")
    facts = {
        "primary": primary,
        "backup": backup,
        "current": current,
        "deviation_threshold": _ratio(threshold),
        "current_deviation": _ratio(deviation),
        "is_challenged": challenged.value if challenged else None,
        "challenge_timelock_s": timelock.value if timelock else None,
    }
    node_id = _node(
        ctx, a, "meta_oracle", "Meta-oracle (primary with challengeable backup)", "meta_oracle", **facts, **extra
    )
    report = OracleReport(a, node_id, "meta_oracle", "meta_oracle", facts=facts)
    for role, addr in (("primary", primary), ("backup", backup)):
        active = addr == current
        note = (
            f"{role} oracle, currently {'ACTIVE' if active else 'inactive'}; the backup takes over only if a "
            f"challenge succeeds (deviation > {facts['deviation_threshold']})"
        )
        child = _child(ctx, report, addr, role, f"{role}Oracle()", depth, note=note)
        if active:
            report.drivers += child.drivers
        else:
            report.alternates += child.drivers + child.alternates
    return report


def _morpho_v2(ctx: Ctx, a: str, depth: int, extra: dict) -> OracleReport:
    getters = {
        g: _get(ctx, a, f"{g}()(address)").value for g in ("BASE_FEED_1", "BASE_FEED_2", "QUOTE_FEED_1", "QUOTE_FEED_2")
    }
    base_vault = _get(ctx, a, "BASE_VAULT()(address)")
    quote_vault = _get(ctx, a, "QUOTE_VAULT()(address)")
    scale = _get(ctx, a, "SCALE_FACTOR()(uint256)").value
    price = _get(ctx, a, "price()(uint256)")
    facts = {
        "scale_factor": str(scale),
        "price_raw": str(price.value) if price else None,
        **{k.lower(): v for k, v in getters.items() if v != ZERO_ADDRESS},
    }
    node_id = _node(ctx, a, "morpho_oracle", "Morpho ChainlinkOracleV2", "morpho_chainlink_v2", **facts, **extra)
    report = OracleReport(a, node_id, "morpho_chainlink_v2", "morpho_chainlink_v2", facts=facts)
    for res, side in ((base_vault, "base"), (quote_vault, "quote")):
        if res and res.value != ZERO_ADDRESS:
            vault = ctx.asset(res.value)
            ctx.graph.edge(
                node_id,
                vault,
                "reads_price_of",
                "exchange_rate",
                ctx.onchain(
                    res, f"oracle converts through the {side} vault's exchange rate (ERC-4626 convertToAssets)"
                ),
                "verified",
            )
            report.drivers.append(Driver("rate", ctx.graph.nodes[vault].label, side))
    for getter, feed in getters.items():
        if feed != ZERO_ADDRESS:
            side = "base" if getter.startswith("BASE") else "quote"
            report.drivers += _child(ctx, report, feed, getter, f"{getter}()", depth, side).drivers
    if all(v == ZERO_ADDRESS for v in getters.values()):
        ctx.graph.nodes[node_id].label = "Morpho ChainlinkOracleV2 (vault rate only, no USD feed)"
        ctx.graph.nodes[node_id].attributes["hardcoded_peg"] = (
            "no feed: one unit of the vault's underlying is valued at exactly one unit of the loan token"
        )
    return report


def _aave_ratio(ctx: Ctx, a: str, depth: int, extra: dict) -> OracleReport:
    provider = _get(ctx, a, "RATIO_PROVIDER()(address)")
    base = _get(ctx, a, "BASE_TO_USD_AGGREGATOR()(address)").value
    ratio = _get(ctx, a, "getRatio()(int256)")
    desc = _get(ctx, a, "description()(string)")
    label = desc.value if desc else "Aave ratio adapter"
    facts = {"description": label, "ratio": str(ratio.value) if ratio else None}
    node_id = _node(
        ctx, a, safe_name("aave." + label), f"Aave price adapter: {label}", "aave_ratio_adapter", **facts, **extra
    )
    report = OracleReport(a, node_id, "aave_ratio_adapter", label, facts=facts)
    vault = ctx.asset(provider.value)
    ctx.graph.edge(
        node_id,
        vault,
        "reads_price_of",
        "exchange_rate",
        ctx.onchain(provider, "adapter multiplies a USD feed by this token's exchange rate"),
        "verified",
    )
    report.drivers.append(Driver("rate", ctx.graph.nodes[vault].label))
    report.drivers += _child(ctx, report, base, "base USD feed", "BASE_TO_USD_AGGREGATOR()", depth).drivers
    return report


def _aave_capped(ctx: Ctx, a: str, depth: int, extra: dict) -> OracleReport:
    feed = _get(ctx, a, "ASSET_TO_USD_AGGREGATOR()(address)").value
    desc = _get(ctx, a, "description()(string)")
    cap = _get(ctx, a, "getPriceCap()(int256)")
    capped = _get(ctx, a, "isCapped()(bool)")
    label = desc.value if desc else "Aave capped feed"
    facts = {
        "description": label,
        "price_cap": str(cap.value) if cap else None,
        "is_capped": capped.value if capped else None,
    }
    node_id = _node(
        ctx, a, safe_name("aave." + label), f"Aave price adapter: {label}", "aave_capped_feed", **facts, **extra
    )
    report = OracleReport(a, node_id, "aave_capped_feed", label, facts=facts)
    report.drivers += _child(ctx, report, feed, "underlying USD feed", "ASSET_TO_USD_AGGREGATOR()", depth).drivers
    return report


def _pendle_discount(ctx: Ctx, a: str, extra: dict) -> OracleReport:
    pt = _get(ctx, a, "PT()(address)")
    discount = _get(ctx, a, "baseDiscountPerYear()(uint256)").value
    maturity = _get(ctx, a, "maturity()(uint256)").value
    answer = _get(ctx, a, "latestRoundData()(uint80,int256,uint256,uint256,uint80)")
    pt_node = ctx.asset(pt.value)
    facts = {
        "base_discount_per_year": _ratio_value(discount),
        "maturity_unix": maturity,
        "answer": str(answer.value[1]) if answer else None,
    }
    label = f"Pendle linear-discount feed for {ctx.graph.nodes[pt_node].label} ({facts['base_discount_per_year']}/yr)"
    node_id = _node(ctx, a, "pendle_linear_discount", label, "pendle_linear_discount", **facts, **extra)
    ctx.graph.edge(
        node_id,
        pt_node,
        "reads_price_of",
        "maturity_redemption",
        ctx.onchain(
            pt,
            "price = 1 - discount x time to maturity: deterministic, ignores the PT's AMM "
            "price and the underlying's market price",
        ),
        "verified",
    )
    return OracleReport(
        a,
        node_id,
        "pendle_linear_discount",
        label,
        [Driver("linear_discount", ctx.graph.nodes[pt_node].label)],
        facts=facts,
    )


def _feed(ctx: Ctx, a: str, extra: dict) -> OracleReport:
    desc = _get(ctx, a, "description()(string)").value
    decimals = _get(ctx, a, "decimals()(uint8)")
    round_data = _get(ctx, a, "latestRoundData()(uint80,int256,uint256,uint256,uint80)").value
    aggregator = _get(ctx, a, "aggregator()(address)")
    facts = {
        "description": desc,
        "decimals": decimals.value if decimals else None,
        "answer": str(round_data[1]),
        "updated_at_unix": round_data[3],
        "aggregator": aggregator.value if aggregator else None,
    }
    if ctx.facts.get("block_timestamp"):
        facts["age_s"] = ctx.facts["block_timestamp"] - round_data[3]
    if "dummy" in desc.lower() or "constant" in desc.lower():
        node_id = _node(
            ctx, a, safe_name("constant." + desc), f"Constant feed: {desc}", "constant_feed", **facts, **extra
        )
        return OracleReport(a, node_id, "constant_feed", desc, [Driver("constant", desc)], facts=facts)

    pair = [p.strip() for p in desc.split("/")]
    if len(pair) != 2 or not all(pair) or any(" " in p for p in pair):
        node_id = _node(
            ctx, a, safe_name("feed." + desc)[:48], f"Price feed '{desc}'", "aggregator_feed", **facts, **extra
        )
        ctx.unresolve(
            node_id, f"feed description '{desc}' does not name a BASE / QUOTE pair: its input is unknown", "oracle"
        )
        return OracleReport(a, node_id, "aggregator_feed", desc, [Driver("unknown", desc)], facts=facts)
    base, quote = pair
    node_id = _node(
        ctx, a, safe_name(f"chainlink.{base}-{quote}"), f"Chainlink {desc} feed", "chainlink_feed", **facts, **extra
    )
    token = ctx.registry.token(base)
    if token:
        asset = ctx.asset(token["address"])
        ctx.graph.edge(
            node_id,
            asset,
            "reads_price_of",
            "oracle_repricing",
            ctx.onchain(
                None,
                f"feed description '{desc}' names {base}; mapped to the registry's {base} "
                "contract by symbol (inference, not an on-chain link)",
                status="to_verify",
                call="description()",
                reference=a,
            ),
            "inferred",
        )
    else:
        ctx.unresolve(node_id, f"feed prices {base}, which is not a registry token: asset node not linked", "oracle")
    return OracleReport(a, node_id, "chainlink_feed", desc, [Driver("feed", f"{base}/{quote}")], facts=facts)


def _ratio(res) -> str | None:
    return _ratio_value(res.value) if res else None


def _ratio_value(raw: int) -> str:
    return f"{raw / 1e18:.6f}".rstrip("0").rstrip(".")


@dataclass
class PassThrough:
    value: str | None  # "1" / "0" / None (unknown)
    oracle_type: str
    explanation: str
    backup_value: str | None = None


def usde_pass_through(report: OracleReport) -> PassThrough:
    """Share of a USDe market-price move that this oracle reports, from its active inputs."""
    if not report.known:
        return PassThrough(None, "unknown", "at least one oracle component could not be classified")
    value, kind, why = _classify(report.drivers)
    backup = None
    if report.alternates:
        backup = _classify(report.alternates)[0]
        why += f"; the inactive backup would give pass-through {backup}"
        kind += "_with_backup"
    return PassThrough(value, kind, why, backup)


def _classify(drivers: list[Driver]) -> tuple[str, str, str]:
    base_feeds = [d.detail for d in drivers if d.kind == "feed" and d.side == "base"]
    tracks = [f for f in base_feeds if f.split("/")[0] in USDE_LIKE]
    has_rate = any(d.kind == "rate" for d in drivers)
    has_discount = any(d.kind == "linear_discount" for d in drivers)
    inputs = ", ".join(f"{d.kind}:{d.detail}" + (" (quote)" if d.side == "quote" else "") for d in drivers) or "none"
    if tracks:
        kind = (
            "pt_discount_x_market_feed"
            if has_discount
            else ("exchange_rate_x_market_feed" if has_rate else "market_price_feed")
        )
        return "1", kind, f"reads a USDe market feed ({', '.join(tracks)}); inputs: {inputs}"
    if has_discount:
        kind = "pt_linear_discount_hardcoded_peg"
    elif has_rate and not base_feeds:
        kind = "exchange_rate_usde_hardcoded"
    elif has_rate:
        kind = "exchange_rate_x_proxy_feed"
    elif base_feeds:
        kind = "proxy_asset_feed"
    else:
        kind = "constant"
    return "0", kind, f"no USDe market feed on the active path; inputs: {inputs}"


def safe_inspect(ctx: Ctx, address: str) -> OracleReport | None:
    try:
        return inspect(ctx, address)
    except (CallReverted, ValueError) as exc:
        ctx.unresolve(f"oracle {address}", f"introspection failed: {exc}", "oracle")
        return None
