"""Import a real wallet: its Ethena-exposed positions on Ethereum, read on-chain at one pinned block.

    python -m backend.discovery wallet --address 0x... --set wallet_<name>

What is read (every amount from an eth_call at the pinned block; APIs only find where to look):
- USDe and sUSDe held directly (balanceOf);
- Pendle PTs on USDe / sUSDe (active markets from the Pendle API, PT balance on-chain);
- Morpho Blue: markets found with the Morpho API, the position itself read from Morpho Blue
  (position + market totals, shares converted to assets): borrows against USDe / sUSDe / their PTs,
  and supplies to markets taking that collateral (the lender bears its bad debt);
- Aave v3 core: aToken and variable-debt balances, the account's eMode.

Positions outside what the engine models (other collateral, other chains) are listed in `skipped`
with the reason, never dropped silently. The output is a portfolio with data_origin=observed;
USD values are filled by revalue_portfolio once discovery has priced the assets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.adapters.aave import RESERVE_DATA
from backend.adapters.base import Registry
from backend.adapters.sources import Cassette, EvmClient, HttpJson, SourceError, utc_now

CONFIRMATIONS = 3
MIN_UNITS = 100  # ignore dust below ~100 USD of a stable-like token
ETHENA = ("USDe", "sUSDe")
DEBT_TOKENS = ("USDC", "USDT", "PYUSD", "USDe")


@dataclass
class WalletImport:
    address: str
    block: int
    observed_at: str
    positions: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def portfolio(self, portfolio_id: str) -> dict:
        return {
            "schema_version": "1.0",
            "portfolio_id": portfolio_id,
            "as_of": self.observed_at,
            "quote_currency": "USD",
            "positions": self.positions,
            "totals": {"gross_value_usd": "0", "debt_value_usd": "0", "net_equity_usd": "0"},
        }


def _slug(*parts: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", "_".join(parts).lower()).strip("_")


def _ethena_collateral(symbol: str) -> bool:
    upper = symbol.upper()
    return symbol in ETHENA or upper.startswith("PT-SUSDE") or upper.startswith("PT-USDE")


def _venue(symbol: str) -> str:
    upper = symbol.upper()
    if upper.startswith("PT-SUSDE"):
        return "venue:pendle_pt_susde"
    if upper.startswith("PT-USDE"):
        return "venue:pendle_pt_usde"
    return f"venue:{_slug(symbol)}_usdc"


def _position(pid: str, protocol: str, kind: str, market_id: str | None, venue: str, **fields) -> dict:
    return {
        "position_id": pid, "protocol": protocol, "chain_id": 1, "position_type": kind, "market_id": market_id,
        **fields,
        "gross_value_usd": "0", "debt_value_usd": "0", "net_equity_usd": "0",
        "exit_venue_id": venue, "data_origin": "observed",
    }


def _units(raw: int, decimals: int) -> str:
    return f"{raw / 10**decimals:.6f}".rstrip("0").rstrip(".")


class _Reader:
    def __init__(self, address: str, mode: str, cassette: Path | None, record: bool):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            raise ValueError(f"not an Ethereum address: {address!r}")
        self.user = address.lower()
        if mode == "replay":
            self.cassette = Cassette("replay", cassette)
        else:
            self.cassette = Cassette("live", cassette if record else None)
        self.evm, self.http = EvmClient(self.cassette), HttpJson(self.cassette)
        self.registry = Registry.load(1)
        self.mode, self.record = mode, record

    def run(self) -> WalletImport:
        if self.evm.chain_id() != 1:
            raise SourceError("the RPC endpoint is not Ethereum mainnet")
        block = self.cassette.meta["block"] if self.mode == "replay" else self.evm.latest_block() - CONFIRMATIONS
        observed_at = self.cassette.meta["observed_at"] if self.mode == "replay" else utc_now()
        self.evm.pin(block)
        out = WalletImport(self.user, block, observed_at)
        self._tokens(out)
        self._pendle(out)
        self._morpho(out)
        self._aave(out)
        if self.record:
            self.cassette.save({"block": block, "observed_at": observed_at, "chain_id": 1, "wallet": self.user,
                                "recorded_by": "backend.discovery.wallet"})
        return out

    # reads -------------------------------------------------------------------------------
    def _balance(self, token: str, owner: str | None = None) -> int:
        return self.evm.call(token, "balanceOf(address)(uint256)", owner or self.user).value

    def _meta(self, token: str) -> tuple[str, int]:
        return (self.evm.call(token, "symbol()(string)").value, self.evm.call(token, "decimals()(uint8)").value)

    def _tokens(self, out: WalletImport) -> None:
        for symbol in ETHENA:
            token = self.registry.token(symbol)["address"]
            raw = self._balance(token)
            if raw >= MIN_UNITS * 10**18:
                unit = "sUSDe_shares" if symbol == "sUSDe" else symbol
                out.positions.append(_position(f"{symbol.lower()}_wallet", "ethena", "token_holding", None, _venue(symbol),
                                               asset_symbol=symbol, quantity=_units(raw, 18), quantity_unit=unit))

    def _pendle(self, out: WalletImport) -> None:
        api = self.registry.protocol("pendle")["api"]
        underlying = {self.registry.token(s)["address"] for s in ETHENA}
        try:
            markets = self.http.get(f"{api}/v1/1/markets/active")["markets"]
        except SourceError as exc:
            out.notes.append(f"Pendle API unavailable, PT holdings not checked: {exc}")
            return
        for m in markets:
            if m.get("underlyingAsset", "").split("-")[-1].lower() not in underlying:
                continue
            pt = m["pt"].split("-")[-1].lower()
            raw = self._balance(pt)
            symbol, decimals = self._meta(pt)
            if raw >= MIN_UNITS * 10**decimals:
                out.positions.append(_position(_slug("pendle", symbol), "pendle", "pt_holding", m["address"].lower(),
                                               _venue(symbol), asset_symbol=symbol, quantity=_units(raw, decimals),
                                               quantity_unit="PT_tokens"))

    def _morpho(self, out: WalletImport) -> None:
        cfg = self.registry.protocol("morpho")
        query = ('{ userByAddress(address: "%s", chainId: 1) { marketPositions { market { marketId '
                 "collateralAsset { address symbol } loanAsset { address symbol } } } } }" % self.user)
        try:
            body = self.http.post(cfg["api"], {"query": query})
        except SourceError as exc:
            out.notes.append(f"Morpho API unavailable, Morpho positions not checked: {exc}")
            return
        if body.get("errors"):  # an address that never used Morpho is "not found"
            return
        for item in body["data"]["userByAddress"]["marketPositions"]:
            market = item["market"]
            if not market.get("collateralAsset"):
                continue
            mid = market["marketId"].lower()
            coll, loan = market["collateralAsset"]["symbol"], market["loanAsset"]["symbol"]
            raw_id = bytes.fromhex(mid[2:])
            supply_shares, borrow_shares, collateral = self.evm.call(
                cfg["morpho_blue"], "position(bytes32,address)(uint256,uint128,uint128)", raw_id, self.user).values
            if not (supply_shares or borrow_shares or collateral):
                continue
            supply_assets, supply_total, borrow_assets, borrow_total, _, _ = self.evm.call(
                cfg["morpho_blue"], "market(bytes32)(uint128,uint128,uint128,uint128,uint128,uint128)", raw_id).values
            loan_dec = self._meta(market["loanAsset"]["address"])[1]
            coll_dec = self._meta(market["collateralAsset"]["address"])[1]
            if not _ethena_collateral(coll):
                out.skipped.append(f"Morpho {coll}/{loan} ({mid}): collateral outside the Ethena scope of the engine")
                continue
            if collateral or borrow_shares:
                debt = -(-borrow_shares * borrow_assets // borrow_total) if borrow_total else 0  # rounded up, as Morpho
                out.positions.append(_position(
                    _slug("morpho", coll, loan), "morpho", "collateralized_borrow", mid, _venue(coll),
                    collateral_asset=coll, collateral_quantity=_units(collateral, coll_dec),
                    debt_asset=loan, debt_quantity=_units(debt, loan_dec)))
            if supply_shares:
                supplied = supply_shares * supply_assets // supply_total if supply_total else 0
                out.positions.append(_position(
                    _slug("morpho_supply", coll, loan), "morpho", "lending_supply", mid,
                    f"venue:{_slug('morpho', coll, loan, 'supply')}",
                    asset_symbol=loan, quantity=_units(supplied, loan_dec), quantity_unit=loan))

    def _aave(self, out: WalletImport) -> None:
        provider = self.registry.protocol("aave")["pool_addresses_providers"]["ethereum_core"]
        pool = self.evm.call(provider, "getPool()(address)").value
        account = self.evm.call(pool, "getUserAccountData(address)(uint256,uint256,uint256,uint256,uint256,uint256)",
                                self.user).values
        if not account[0] and not account[1]:
            return
        emode = self.evm.call(pool, "getUserEMode(address)(uint256)", self.user).value
        collateral, debts = {}, {}
        for symbol in dict.fromkeys(ETHENA + DEBT_TOKENS):
            asset = self.registry.token(symbol)["address"]
            data = self.evm.try_call(pool, RESERVE_DATA, asset)
            if data is None:
                continue
            a_token, variable_debt = data.values[8], data.values[10]
            if symbol in ETHENA and (raw := self._balance(a_token)) >= MIN_UNITS * 10**18:
                collateral[symbol] = raw / 10**18
            decimals = self._meta(asset)[1]
            if (raw := self._balance(variable_debt)) >= MIN_UNITS * 10**decimals:
                debts[symbol] = raw / 10**decimals
        total_collateral_usd = account[0] / 1e8
        modelled_usd = sum(collateral.values())  # stable-like, ~1 USD per unit (sUSDe slightly more)
        if total_collateral_usd > 1.25 * modelled_usd + MIN_UNITS:
            out.skipped.append(f"Aave: {total_collateral_usd - modelled_usd:,.0f} USD of collateral in assets outside "
                               "the Ethena scope; only the USDe / sUSDe part is modelled")
        if not collateral:
            return
        if not debts:
            debts = {"USDC": 0.0}
        total_debt = sum(debts.values()) or 1.0
        total_coll = sum(collateral.values())
        market_id = f"{provider}#emode={emode}" if emode else provider
        for coll, c_qty in collateral.items():
            for debt, d_qty in debts.items():
                out.positions.append(_position(
                    _slug("aave", coll, debt), "aave", "collateralized_borrow", market_id, _venue(coll),
                    collateral_asset=coll, collateral_quantity=f"{c_qty * (d_qty / total_debt if d_qty else 1):.6f}",
                    debt_asset=debt, debt_quantity=f"{d_qty * c_qty / total_coll:.6f}"))
        if len(collateral) * len(debts) > 1:
            out.notes.append("Aave account is cross-margined: its collateral and debt are split pro rata into one "
                             "position per collateral/debt pair; each pair is checked against the same liquidation "
                             "threshold, which approximates the account's single health factor.")


def import_wallet(address: str, mode: str = "live", cassette: Path | None = None, record: bool = False) -> WalletImport:
    return _Reader(address, mode, cassette, record).run()


FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
CASSETTES = Path(__file__).resolve().parent / "cassettes"
PRESETS = "stress_portfolio_01"  # scenario requests reused, re-addressed to the wallet set


def build_set(address: str, folder: Path, mode: str = "live", surface: bool = True) -> dict:
    """Wallet -> fixture set: import, live discovery (both recorded for replay), revaluation, the scenario
    presets, then every risk result, analytics, crisis plan and the offline risk surface."""
    from backend.discovery.service import discover, revalue_portfolio
    from backend.risk.regenerate import regenerate

    set_id = folder.name
    live = mode == "live"
    wallet = import_wallet(address, mode, CASSETTES / f"{set_id}_wallet.json", record=live)
    if not wallet.positions:
        if live:  # nothing to build: keep no recording of it
            (CASSETTES / f"{set_id}_wallet.json").unlink(missing_ok=True)
        raise ValueError(f"{address}: no Ethena-exposed position found at block {wallet.block}; skipped: {wallet.skipped}")
    ids = {"portfolio_id": f"{set_id}_portfolio", "graph_id": f"graph_{set_id}", "snapshot_id": f"snapshot_{set_id}"}
    graph, snapshot = discover(wallet.portfolio(ids["portfolio_id"]), mode, cassette=CASSETTES / f"{set_id}.json",
                               record=live, graph_id=ids["graph_id"], snapshot_id=ids["snapshot_id"])
    portfolio, valuation_warnings = revalue_portfolio(wallet.portfolio(ids["portfolio_id"]), snapshot)
    origin = f"Wallet {wallet.address} read on-chain at block {wallet.block} ({wallet.observed_at})."
    snapshot["warnings"] = [origin, *wallet.skipped, *wallet.notes, *valuation_warnings, *snapshot["warnings"]]

    folder.mkdir(parents=True, exist_ok=True)
    files = {"portfolio": portfolio, "market_snapshot": snapshot, "dependency_graph": graph}
    for request_file in sorted((FIXTURES / PRESETS).glob("scenario_request*.json")):
        request = json.loads(request_file.read_text())
        request.update(request_id=f"{set_id}_{request_file.stem}", portfolio_id=ids["portfolio_id"],
                       graph_id=ids["graph_id"], snapshot_id=ids["snapshot_id"])
        files[request_file.stem] = request
    for name, content in files.items():
        (folder / f"{name}.json").write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")
    schema = lambda n: "scenario_request" if n.startswith("scenario_request") else n  # noqa: E731
    manifest = {
        "schema_version": "1.0", "fixture_set_id": set_id,
        "description": f"Real wallet {wallet.address}: positions read on Ethereum at block {wallet.block} "
                       f"({wallet.observed_at}). Built by backend/discovery/wallet.py.",
        "ids": ids,
        "files": {n: {"path": f"{n}.json", "schema": f"../../schemas/v1/{schema(n)}.schema.json"} for n in files},
        "golden": False,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    regenerate(folder, surface=surface)
    return {"block": wallet.block, "positions": [p["position_id"] for p in portfolio["positions"]],
            "net_equity_usd": portfolio["totals"]["net_equity_usd"], "skipped": wallet.skipped, "notes": wallet.notes}
