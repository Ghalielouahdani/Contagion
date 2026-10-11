"""Command line for the discovery module.

python -m backend.discovery discover --portfolio PATH [--mode live|replay|fixture] [--cassette PATH] [--record]
                                     [--out DIR] [--revalue]
python -m backend.discovery wallet   --address 0x... --set wallet_<name> [--mode live|replay] [--no-surface]
python -m backend.discovery explain  --graph PATH --position ID
python -m backend.discovery impacted --graph PATH --node NODE_ID
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.discovery.coverage import LAYERS
from backend.discovery.explorer import Limits
from backend.discovery.query import explain, impacted_by
from backend.discovery.service import DiscoveryError, discover, revalue_portfolio

SHORT = {
    "settlement_chain": "chain",
    "yield_source_and_issuer": "yield/issuer",
    "oracle": "oracle",
    "market_and_liquidity": "market/AMM/exit",
    "lending_collateral_market": "lending",
}


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _summary(graph: dict, snapshot: dict) -> str:
    lines = [
        f"graph {graph['graph_id']}: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
        f"block {graph.get('block_number')}, as of {graph['as_of']}"
    ]
    coverage = graph.get("coverage") or {}
    if coverage:
        width = max(len(p) for p in coverage) + 2
        lines.append("".ljust(width) + "".join(SHORT[layer].ljust(18) for layer in LAYERS))
        for pid, cov in coverage.items():
            lines.append(pid.ljust(width) + "".join(cov["layers"][layer]["status"].ljust(18) for layer in LAYERS))
    for pid, m in snapshot["markets"].items():
        extra = m.get("oracle_type")
        lines.append(
            f"  {pid}: {m['market_kind']}"
            + (
                f", oracle {extra}, pass-through {m.get('oracle_pass_through')}"
                if extra
                else f", implied APY {m.get('pt_implied_apy')}"
            )
        )
    for vid, v in snapshot["exit_venues"].items():
        lines.append(f"  {vid}: {v['quote_method']}, depth {v['effective_depth_usd']} USD ({v['source_type']})")
    lines.append(f"unresolved: {len(graph.get('unresolved', []))}, warnings: {len(graph['warnings'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="portfolio -> dependency_graph.json + market_snapshot.json")
    d.add_argument("--portfolio", type=Path, required=True)
    d.add_argument("--mode", choices=("fixture", "live", "replay"), default="live")
    d.add_argument("--cassette", type=Path, help="record to (with --record) or replay from this file")
    d.add_argument("--record", action="store_true")
    d.add_argument("--out", type=Path, help="directory for dependency_graph.json and market_snapshot.json")
    d.add_argument("--graph-id")
    d.add_argument("--snapshot-id")
    d.add_argument("--revalue", action="store_true", help="also write portfolio.json revalued at snapshot prices")
    d.add_argument("--max-depth", type=int, default=Limits.max_depth)
    d.add_argument("--max-entities", type=int, default=Limits.max_entities)

    e = sub.add_parser("explain", help="five-layer view of one position")
    e.add_argument("--graph", type=Path, required=True)
    e.add_argument("--position", required=True)

    i = sub.add_parser("impacted", help="positions depending on a component, with their paths")
    i.add_argument("--graph", type=Path, required=True)
    i.add_argument("--node", required=True)

    w = sub.add_parser("wallet", help="real wallet -> fixture set (positions read on-chain, discovery, risk results)")
    w.add_argument("--address", required=True)
    w.add_argument("--set", required=True, help="fixture set name, e.g. wallet_cf0a12")
    w.add_argument("--mode", choices=("live", "replay"), default="live")
    w.add_argument("--no-surface", action="store_true", help="skip the offline risk surface (faster)")

    args = parser.parse_args(argv)
    if args.command == "wallet":
        from backend.discovery.wallet import FIXTURES, build_set

        try:
            print(json.dumps(build_set(args.address, FIXTURES / args.set, args.mode, not args.no_surface), indent=2))
        except (DiscoveryError, ValueError) as exc:
            print(f"wallet import failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "explain":
        print(explain(json.loads(args.graph.read_text()), args.position))
        return 0
    if args.command == "impacted":
        try:
            rows = impacted_by(json.loads(args.graph.read_text()), args.node)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(json.dumps(rows, indent=2))
        return 0

    portfolio = json.loads(args.portfolio.read_text())
    try:
        graph, snapshot = discover(
            portfolio,
            args.mode,
            cassette=args.cassette,
            record=args.record,
            graph_id=args.graph_id,
            snapshot_id=args.snapshot_id,
            limits=Limits(max_depth=args.max_depth, max_entities=args.max_entities),
        )
    except DiscoveryError as exc:
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 1
    print(_summary(graph, snapshot))
    if args.out:
        _write(args.out / "dependency_graph.json", graph)
        _write(args.out / "market_snapshot.json", snapshot)
        written = ["dependency_graph.json", "market_snapshot.json"]
        if args.revalue:
            revalued, warnings = revalue_portfolio(portfolio, snapshot)
            _write(args.out / "portfolio.json", revalued)
            written.append("portfolio.json")
            for w in warnings:
                print(f"revalue: {w}", file=sys.stderr)
        print(f"wrote {', '.join(written)} to {args.out}")
    return 0
