"""Build a verified lender fixture set from live Morpho Blue markets.

Usage: python -m backend.discovery.build_lending_set contracts/fixtures/<set_name>

Holdings are fictional (LENDERS below); everything else is read at one pinned block: market
parameters and totals, the oracle and its feeds, prices, the sUSDe exchange rate, supply APYs
and the real borrower LTV distribution (coverage reconciled with on-chain debt). Then run
the engine on the requests (risk results) and `python -m backend.risk.surface <set>`.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path

from backend.discovery import morpho
from backend.discovery.onchain import as_uint, call, latest_block, post_json, uint_arg

SUSDE = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"
FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"

# Fictional lender holdings on real markets: (position id, Morpho market id, amount supplied in loan asset)
LENDERS = [
    ("lend_susde_01", "0x90ef0c5a0dc7c4de4ad4585002d44e9d411d212d2f6258e94948beecf8b4c0d5", 5_000_000),  # sUSDe / PYUSD
    ("lend_usde_01", "0xd9d2fc090bdbab1804ea960dd6669b62357787e5816f575f14ca4e6d999614bf", 3_000_000),  # USDe / RLUSD
]
# Scenario requests reuse the presets of the demo sets, re-addressed to this set.
REQUEST_PRESETS = {
    "scenario_request": ("demo_lending_01", "scenario_request"),
    "scenario_request_liquidity": ("demo_lending_01", "scenario_request_liquidity"),
    "scenario_request_carry": ("demo_lending_01", "scenario_request_carry"),
    "scenario_request_combined": ("demo_ethena_01", "scenario_request_combined"),
    "scenario_request_governance": ("demo_ethena_01", "scenario_request_governance"),
    "scenario_request_node_shock": ("demo_ethena_01", "scenario_request_node_shock"),
}


def market_apys(market_id: str) -> dict:
    """Current supply / borrow APY of a market from the Morpho indexer."""
    query = '{ markets(where: { uniqueKey_in: ["%s"], chainId_in: [1] }) { items { state { supplyApy borrowApy } } } }' % market_id
    items = post_json(morpho.MORPHO_API, {"query": query})["data"]["markets"]["items"]
    return items[0]["state"] if items else {}


def build(folder: Path) -> None:
    block = latest_block()
    as_of = dt.datetime.fromtimestamp(block.timestamp, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    set_id = folder.name
    ids = {"portfolio_id": f"{set_id}_portfolio", "graph_id": f"graph_{set_id}", "snapshot_id": f"snapshot_{set_id}"}
    susde_rate = as_uint(call(SUSDE, "convertToAssets(uint256)", uint_arg(10**18), block=block.number)) / 10**18

    positions, markets, yields, prices, provenance = [], {}, {}, {}, {}
    nodes = {
        "asset:USDe": ("asset", "USDe"), "asset:sUSDe": ("asset", "sUSDe"), "protocol:ethena": ("protocol", "Ethena"),
        "protocol:morpho": ("protocol", "Morpho Blue"), "offchain:ethena_backing": ("offchain_entity", "Ethena backing (custody, hedges, reserve fund)"),
    }
    edges = [
        ("asset:USDe", "protocol:ethena", "issued_by", "issuer_backing", "documented", "https://docs.ethena.fi/"),
        ("asset:USDe", "offchain:ethena_backing", "backed_by", "custody", "documented", "https://docs.ethena.fi/"),
        ("asset:sUSDe", "asset:USDe", "redeemable_for", "exchange_rate", "verified",
         f"sUSDe {SUSDE}.convertToAssets(1e18) = {susde_rate:.6f} USDe"),
        ("asset:sUSDe", "protocol:ethena", "issued_by", "smart_contract", "documented", "https://docs.ethena.fi/"),
    ]

    for position_id, market_id, amount in LENDERS:
        m = morpho.read_market(market_id, block.number)
        pass_through, oracle_type = morpho.oracle_pass_through(m)
        dist = morpho.ltv_distribution(m, morpho.borrower_positions(market_id))
        apys = market_apys(market_id)
        for name, f in m.oracle_feeds.items():
            if isinstance(f, dict) and "description" in f:
                base, _, quote = f["description"].partition(" / ")
                if quote == "USD":
                    prices[base] = f["answer"]
        venue = f"venue:morpho_{m.collateral_symbol.lower()}_{m.loan_symbol.lower()}_supply"
        market_node, oracle_node, loan_node = f"market:{position_id}", f"oracle:{position_id}", f"asset:{m.loan_symbol}"
        positions.append({
            "position_id": position_id, "protocol": "morpho", "chain_id": 1, "position_type": "lending_supply",
            "market_id": market_id, "asset_symbol": m.loan_symbol, "quantity": str(amount), "quantity_unit": m.loan_symbol,
            "gross_value_usd": f"{amount:.2f}", "debt_value_usd": "0", "net_equity_usd": f"{amount:.2f}",
            "exit_venue_id": venue, "data_origin": "fictional",
        })
        markets[position_id] = {
            "market_kind": "morpho_blue_market",
            "lltv": f"{m.lltv:.4f}",
            "liquidation_incentive": f"{m.liquidation_incentive:.4f}",
            "oracle_pass_through": f"{pass_through:.1f}",
            "oracle_type": oracle_type,
            "oracle_address": m.oracle,
            "collateral_asset": m.collateral_symbol,
            "loan_asset": m.loan_symbol,
            "total_supply_assets": f"{m.total_supply_assets:.2f}",
            "total_borrow_assets": f"{m.total_borrow_assets:.2f}",
            "borrower_ltv_buckets": dist["buckets"],
            "borrower_distribution_source_type": "observed",
            "verified": True,
            "source_type": "observed",
            "field_sources": {"liquidation_incentive": "derived", "oracle_pass_through": "derived", "borrower_ltv_buckets": "derived"},
            "warnings": [
                f"Borrower distribution from {dist['borrowers']} indexed positions (Morpho API) at oracle prices; "
                f"{dist['coverage']:.2%} of on-chain debt covered.",
            ],
        }
        yields[position_id] = {"token_apy": f"{apys.get('supplyApy', 0):.4f}", "source_type": "observed"}
        provenance[position_id] = {"market": market_id, "borrowers": dist["borrowers"], "coverage": round(dist["coverage"], 6),
                                   "liquidatable_now_share": round(dist["liquidatable_now_share"], 6)}

        nodes.update({
            f"position:{position_id}": ("position", f"{m.loan_symbol} supplied to Morpho {m.collateral_symbol}/{m.loan_symbol}"),
            market_node: ("market", f"Morpho {m.collateral_symbol}/{m.loan_symbol} {m.lltv:.1%} LLTV"),
            oracle_node: ("oracle", f"Morpho oracle {oracle_type.split(':', 1)[-1]}"),
            loan_node: ("asset", m.loan_symbol),
            venue: ("venue", f"{m.loan_symbol} withdrawal from idle market liquidity"),
        })
        params_ref = f"Morpho {morpho.MORPHO_BLUE}.idToMarketParams({market_id})"
        edges += [
            (f"position:{position_id}", market_node, "position_in", "borrower_default", "verified", "portfolio input (fictional holdings, data_origin=fictional)"),
            (market_node, f"asset:{m.collateral_symbol}", "collateral_asset", "mark_to_market", "verified", f"{params_ref}.collateralToken = {m.collateral_token}"),
            (market_node, loan_node, "debt_asset", "debt_cost", "verified", f"{params_ref}.loanToken = {m.loan_token}"),
            (market_node, oracle_node, "prices_collateral_with", "oracle_repricing", "verified", f"{params_ref}.oracle = {m.oracle}"),
            (market_node, "protocol:morpho", "part_of_protocol", "smart_contract", "verified", f"market created on Morpho Blue {morpho.MORPHO_BLUE}"),
            (f"position:{position_id}", venue, "exits_via", "exit_liquidity", "verified", "portfolio input (fictional holdings, data_origin=fictional)"),
        ]
        vault = m.oracle_feeds.get("BASE_VAULT")
        if vault:
            edges.append((oracle_node, f"asset:{vault['symbol']}", "reads_price_of", "exchange_rate", "verified", f"{m.oracle}.BASE_VAULT() = {vault['address']}"))
        for name, f in m.oracle_feeds.items():
            if name.startswith("BASE_FEED"):
                asset = f["description"].split(" / ")[0]
                edges.append((oracle_node, f"asset:{asset}", "reads_price_of", "oracle_repricing", "verified",
                              f"{m.oracle}.{name}() = {f['address']} ('{f['description']}')"))

    stable_prices = {k: v for k, v in prices.items() if k != "USDe"}
    portfolio = {
        "schema_version": "1.0", "portfolio_id": ids["portfolio_id"], "as_of": as_of, "quote_currency": "USD", "positions": positions,
        "totals": {"gross_value_usd": f"{sum(p[2] for p in LENDERS):.2f}", "debt_value_usd": "0.00", "net_equity_usd": f"{sum(p[2] for p in LENDERS):.2f}"},
    }
    snapshot = {
        "schema_version": "1.0", "snapshot_id": ids["snapshot_id"], "as_of": as_of, "chain_id": 1, "block_number": block.number,
        "prices_usd": {"USDe": {"value": f"{prices.get('USDe', 1.0):.6f}", "source_type": "observed"},
                       "sUSDe": {"value": f"{susde_rate * prices.get('USDe', 1.0):.6f}", "source_type": "derived"},
                       **{k: {"value": f"{v:.6f}", "source_type": "observed"} for k, v in stable_prices.items()}},
        "exchange_rates": {"sUSDe_USDe": {"value": f"{susde_rate:.6f}", "source_type": "observed"}},
        "markets": markets, "yields": yields, "exit_venues": {},
        "warnings": ["Markets, oracles, prices, APYs and borrower distributions observed on Ethereum mainnet at the block above; "
                     "lender holdings are fictional. Lenders exit through the market's idle liquidity, not a DEX."],
    }
    graph = {
        "schema_version": "1.0", "graph_id": ids["graph_id"], "portfolio_id": ids["portfolio_id"], "as_of": as_of,
        "nodes": [{"id": i, "type": t, "label": label} for i, (t, label) in nodes.items()],
        "edges": [{"id": f"edge:{k}", "source": s, "target": t, "relation": rel, "risk_channel": ch, "confidence": conf,
                   "evidence": {"method": "onchain_call" if conf == "verified" and not ref.startswith("portfolio") else
                                "fixture" if ref.startswith("portfolio") else "protocol_documentation",
                                "reference": ref, "observed_at": as_of,
                                "status": "verified" if conf == "verified" else "documented",
                                "block_number": block.number if conf == "verified" and not ref.startswith("portfolio") else None}}
                  for k, (s, t, rel, ch, conf, ref) in enumerate(edges, 1)],
        "warnings": ["Edges verified by eth_call at the snapshot block; Ethena issuance and backing are documented, not observable on-chain."],
    }

    folder.mkdir(parents=True, exist_ok=True)
    files = {"portfolio": portfolio, "market_snapshot": snapshot, "dependency_graph": graph}
    for name, (source_set, source_file) in REQUEST_PRESETS.items():
        request = copy.deepcopy(json.loads((FIXTURES / source_set / f"{source_file}.json").read_text()))
        request.update(request_id=f"{set_id}_{source_file.removeprefix('scenario_request').lstrip('_') or 'depeg'}",
                       portfolio_id=ids["portfolio_id"], graph_id=ids["graph_id"], snapshot_id=ids["snapshot_id"])
        files[name] = request
    for name, content in files.items():
        (folder / f"{name}.json").write_text(json.dumps(content, indent=2) + "\n")
    schema = lambda n: "scenario_request" if n.startswith("scenario_request") else n  # noqa: E731
    manifest = {
        "schema_version": "1.0", "fixture_set_id": set_id,
        "description": f"Fictional lender holdings on real Morpho Blue markets read at block {block.number} ({as_of}), "
                       "with the real borrower LTV distribution. Built by backend/discovery/build_lending_set.py.",
        "ids": ids,
        "files": {n: {"path": f"{n}.json", "schema": f"../../schemas/v1/{schema(n)}.schema.json"} for n in files},
        "golden": False,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"block": block.number, "as_of": as_of, "sUSDe_rate": susde_rate, "prices": prices, "markets": provenance}, indent=2))


if __name__ == "__main__":
    build(Path(sys.argv[1]))
