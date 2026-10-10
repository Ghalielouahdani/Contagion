"""Morpho Blue market discovery: parameters, oracle behaviour and the real borrower distribution.

On-chain (pinned to one block): market params, totals, oracle price and the oracle's feeds.
Indexer (Morpho API): every borrower position, used to build the debt distribution by oracle
LTV that the lender model needs (backend/risk/lending.py). The indexed debt is reconciled with
the on-chain total and the coverage is reported, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.discovery.onchain import (
    ZERO_ADDRESS,
    as_address,
    as_uint,
    bytes32_arg,
    call,
    erc20,
    feed,
    post_json,
)

MORPHO_BLUE = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
MORPHO_API = "https://api.morpho.org/graphql"
WAD = 10**18
ORACLE_SCALE = 10**36

# LTV bucket upper edges; the last bucket runs to LLTV, then one bucket for already-liquidatable debt.
BUCKET_EDGES = (0.50, 0.70, 0.80, 0.86, 0.90)
MAX_LTV = 10.0  # cap for positions with (almost) no collateral left


@dataclass(frozen=True)
class MorphoMarket:
    market_id: str
    block: int
    loan_token: str
    loan_symbol: str
    loan_decimals: int
    collateral_token: str
    collateral_symbol: str
    collateral_decimals: int
    oracle: str
    irm: str
    lltv: float
    total_supply_assets: float  # loan asset units
    total_borrow_assets: float
    oracle_price: int  # raw: collateral raw units -> loan raw units, scaled by 1e36
    oracle_feeds: dict  # BASE_VAULT, BASE_FEED_1, ... -> address or feed description

    @property
    def liquidation_incentive(self) -> float:
        """Morpho Blue: LIF = min(1.15, 1 / (0.3 x LLTV + 0.7)); incentive = LIF - 1."""
        return min(1.15, 1 / (0.3 * self.lltv + 0.7)) - 1

    @property
    def collateral_price_in_loan(self) -> float:
        return self.oracle_price / ORACLE_SCALE * 10 ** (self.collateral_decimals - self.loan_decimals)


def read_market(market_id: str, block: int) -> MorphoMarket:
    params = call(MORPHO_BLUE, "idToMarketParams(bytes32)", bytes32_arg(market_id), block=block)
    loan, collateral, oracle, irm = (as_address(params, i) for i in range(4))
    lltv = as_uint(params, 4) / WAD
    state = call(MORPHO_BLUE, "market(bytes32)", bytes32_arg(market_id), block=block)
    loan_symbol, loan_decimals = erc20(loan, block)
    collateral_symbol, collateral_decimals = erc20(collateral, block)
    return MorphoMarket(
        market_id=market_id,
        block=block,
        loan_token=loan,
        loan_symbol=loan_symbol,
        loan_decimals=loan_decimals,
        collateral_token=collateral,
        collateral_symbol=collateral_symbol,
        collateral_decimals=collateral_decimals,
        oracle=oracle,
        irm=irm,
        lltv=lltv,
        total_supply_assets=as_uint(state, 0) / 10**loan_decimals,
        total_borrow_assets=as_uint(state, 2) / 10**loan_decimals,
        oracle_price=as_uint(call(oracle, "price()", block=block)),
        oracle_feeds=_oracle_feeds(oracle, block),
    )


def _oracle_feeds(oracle: str, block: int) -> dict:
    """Decode a MorphoChainlinkOracleV2: which vault and which feeds make the price."""
    feeds = {}
    for name in ("BASE_VAULT", "BASE_FEED_1", "BASE_FEED_2", "QUOTE_VAULT", "QUOTE_FEED_1", "QUOTE_FEED_2"):
        try:
            address = as_address(call(oracle, f"{name}()", block=block))
        except RuntimeError:
            return {"decoded": False}
        if address == ZERO_ADDRESS:
            continue
        feeds[name] = feed(address, block) if "FEED" in name else {"address": address, "symbol": erc20(address, block)[0]}
    feeds["decoded"] = True
    return feeds


def oracle_pass_through(market: MorphoMarket) -> tuple[float, str]:
    """1.0 when a base feed prices the collateral's market (e.g. Chainlink USDe/USD); 0.0 when the
    oracle is a vault exchange rate with the underlying hardcoded at 1 USD. Unknown -> 1.0, flagged."""
    feeds = market.oracle_feeds
    if not feeds.get("decoded"):
        return 1.0, "unknown_oracle_assumed_market_feed"
    base = [f["description"] for k, f in feeds.items() if k.startswith("BASE_FEED")]
    vault = feeds.get("BASE_VAULT", {}).get("symbol")
    if base:
        return 1.0, "morpho_chainlink_v2:" + ("vault " + vault + " x " if vault else "") + " x ".join(base)
    return 0.0, "morpho_chainlink_v2:" + (f"vault {vault} only, underlying hardcoded at 1 USD" if vault else "constant price")


def borrower_positions(market_id: str, page: int = 500) -> list[dict]:
    """Every position with debt in the market, from the Morpho indexer (raw integer units)."""
    rows, skip = [], 0
    while True:
        query = (
            "{ marketPositions(first: %d, skip: %d, orderBy: BorrowShares, orderDirection: Desc, "
            'where: { marketUniqueKey_in: ["%s"], borrowShares_gte: "1" }) '
            "{ items { user { address } state { collateral borrowAssets } } } }" % (page, skip, market_id)
        )
        items = post_json(MORPHO_API, {"query": query})["data"]["marketPositions"]["items"]
        rows += [{"user": i["user"]["address"], "collateral": int(i["state"]["collateral"]), "borrow": int(i["state"]["borrowAssets"])}
                 for i in items if i["state"] and int(i["state"]["borrowAssets"]) > 0]
        if len(items) < page:
            return rows
        skip += page


def ltv_distribution(market: MorphoMarket, positions: list[dict]) -> dict:
    """Debt buckets by oracle LTV (debt-weighted mean LTV per bucket), reconciled with on-chain debt."""
    edges = [e for e in BUCKET_EDGES if e < market.lltv] + [market.lltv]
    buckets: list[list[float]] = [[0.0, 0.0] for _ in range(len(edges) + 1)]  # [debt, debt x ltv]
    for p in positions:
        collateral_value = p["collateral"] * market.oracle_price / ORACLE_SCALE  # loan raw units
        ltv = min(p["borrow"] / collateral_value, MAX_LTV) if collateral_value > 0 else MAX_LTV
        index = next((i for i, edge in enumerate(edges) if ltv < edge), len(edges))
        buckets[index][0] += p["borrow"]
        buckets[index][1] += p["borrow"] * ltv
    indexed_debt = sum(b[0] for b in buckets)
    rows = [{"ltv": f"{b[1] / b[0]:.4f}", "debt_share": f"{b[0] / indexed_debt:.4f}"} for b in buckets if b[0] > 0]
    rows = [r for r in rows if float(r["debt_share"]) > 0]  # dust buckets round to 0: their debt goes to the residue
    # debt shares are rounded to 4 dp; push the rounding residue onto the largest bucket so they sum to 1
    residue = 1 - sum(float(r["debt_share"]) for r in rows)
    largest = max(rows, key=lambda r: float(r["debt_share"]))
    largest["debt_share"] = f"{float(largest['debt_share']) + residue:.4f}"
    onchain_debt_raw = market.total_borrow_assets * 10**market.loan_decimals
    return {
        "buckets": rows,
        "borrowers": len(positions),
        "coverage": indexed_debt / onchain_debt_raw if onchain_debt_raw else 0.0,
        "liquidatable_now_share": buckets[-1][0] / indexed_debt if indexed_debt else 0.0,
    }
