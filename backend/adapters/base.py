"""Common adapter interface and discovery context.

An adapter answers one question: "given this entity (a token, a market, an oracle...),
what does it depend on?" It writes typed nodes and evidence-backed edges into the shared
graph and returns the entities to explore next. The explorer (backend/discovery) runs the
adapters breadth-first with a visited set and depth/size/time limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.adapters.sources import CallResult, EvmClient, HttpJson
from backend.discovery.graph import Evidence, GraphBuilder

REGISTRY_DIR = Path(__file__).resolve().parent / "registry"
ZERO_ADDRESS = "0x" + "0" * 40


@dataclass(frozen=True)
class Entity:
    kind: str  # token | pendle_market | morpho_market | aave_market | collateral_scan
    key: str  # lowercase address or market id
    hint: tuple = ()  # immutable extra context, e.g. (("position_id", "aave_01"), ("emode", 11))

    def get(self, name: str, default: Any = None) -> Any:
        return dict(self.hint).get(name, default)


@dataclass
class Registry:
    raw: dict

    @classmethod
    def load(cls, chain_id: int) -> Registry:
        path = REGISTRY_DIR / {1: "ethereum.json"}.get(chain_id, f"chain_{chain_id}.json")
        if not path.exists():
            raise ValueError(f"no protocol registry for chain {chain_id}")
        return cls(json.loads(path.read_text()))

    @property
    def chain_node(self) -> str:
        return self.raw["chain_node"]

    def token(self, symbol: str) -> dict | None:
        return self.raw["tokens"].get(symbol)

    def token_by_address(self, address: str) -> tuple[str, dict] | None:
        for symbol, entry in self.raw["tokens"].items():
            if entry["address"] == address.lower():
                return symbol, entry
        return None

    def issuer(self, key: str) -> dict:
        return self.raw["issuers"][key]

    def protocol(self, key: str) -> dict:
        return self.raw["protocols"][key]


@dataclass
class TokenMeta:
    address: str
    symbol: str
    name: str | None
    decimals: int


@dataclass
class Ctx:
    """Everything an adapter needs, plus the shared outputs it writes to."""

    evm: EvmClient
    http: HttpJson
    registry: Registry
    graph: GraphBuilder
    chain_id: int
    block: int | None
    observed_at: str
    market_params: dict[str, dict] = field(default_factory=dict)  # position_id -> snapshot market object
    yields: dict[str, dict] = field(default_factory=dict)  # position_id -> snapshot yield object
    facts: dict[str, Any] = field(default_factory=dict)  # cross-adapter facts (rates, prices, scans)
    unresolved: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    position_markets: dict[str, str] = field(default_factory=dict)  # market address/id -> position_id
    pending_tokens: list[str] = field(default_factory=list)  # assets created as a side effect, to explore next
    _tokens: dict[str, TokenMeta] = field(default_factory=dict)

    # evidence helpers --------------------------------------------------------------------
    def onchain(
        self,
        result: CallResult | None,
        note: str,
        status: str = "verified",
        call: str | None = None,
        reference: str | None = None,
    ) -> Evidence:
        return Evidence(
            method="onchain_call",
            reference=reference or (result.to if result else "eth_call"),
            observed_at=self.observed_at,
            status=status,
            block_number=self.block,
            call=call or (_short_call(result) if result else None),
            note=note,
        )

    def api(
        self, url: str, note: str, call: str | None = None, method: str = "protocol_api", status: str = "verified"
    ) -> Evidence:
        return Evidence(method=method, reference=url, observed_at=self.observed_at, status=status, call=call, note=note)

    def doc(self, url: str, note: str) -> Evidence:
        return Evidence(
            method="protocol_documentation", reference=url, observed_at=self.observed_at, status="documented", note=note
        )

    def unresolve(self, subject: str, reason: str, layer: str | None = None) -> None:
        item = {"subject": subject, "reason": reason}
        if layer:
            item["layer"] = layer
        if item not in self.unresolved:
            self.unresolved.append(item)

    # token helpers -----------------------------------------------------------------------
    def token_meta(self, address: str) -> TokenMeta:
        address = address.lower()
        if address in self._tokens:
            return self._tokens[address]
        symbol = self._string(address, "symbol")
        name = self._string(address, "name")
        decimals_call = self.evm.try_call(address, "decimals()(uint8)")
        if symbol is None or decimals_call is None:
            raise ValueError(f"{address} does not behave like an ERC-20 (symbol/decimals unreadable)")
        meta = TokenMeta(address, symbol, name, int(decimals_call.value))
        self._tokens[address] = meta
        return meta

    def _string(self, address: str, fn: str) -> str | None:
        res = self.evm.try_call(address, f"{fn}()(string)")
        if res is not None:
            return res.value
        res = self.evm.try_call(address, f"{fn}()(bytes32)")  # e.g. MKR-style tokens
        return res.value.rstrip(b"\x00").decode(errors="replace") if res is not None else None

    def asset(self, address: str) -> str:
        """Node id of the asset at address: created with on-chain metadata and its settlement-chain edge."""
        address = address.lower()
        bound = self.graph.node_for_address(self.chain_id, address)
        if bound:
            return bound
        meta = self.token_meta(address)
        known = self.registry.token_by_address(address)
        name = known[0] if known else meta.symbol
        if known and known[0] != meta.symbol:
            self.warnings.append(f"registry symbol {known[0]} differs from on-chain symbol {meta.symbol} at {address}")
        node_id = self.graph.allocate_id("asset", name, self.chain_id, address)
        self.graph.node(
            node_id,
            "asset",
            meta.symbol,
            address=address,
            chain_id=self.chain_id,
            decimals=meta.decimals,
            name=meta.name,
        )
        self.graph.bind_address(node_id, self.chain_id, address)
        self.settle(node_id, address)
        self.pending_tokens.append(address)
        return node_id

    def settle(self, node_id: str, address: str) -> None:
        """Layer 1: the contract exists on this chain at the pinned block."""
        code = self.evm.get_code(address)
        if not code["size"]:
            self.unresolve(node_id, f"no contract code at {address} on chain {self.chain_id}", "settlement_chain")
            return
        self.graph.edge(
            node_id,
            self.registry.chain_node,
            "deployed_on",
            "settlement",
            self.onchain(
                None,
                f"contract code present ({code['size']} bytes) at the pinned block",
                call="eth_getCode",
                reference=address,
            ),
            "verified",
        )

    def protocol_node(self, key: str) -> str:
        p = self.registry.protocol(key)
        return self.graph.node(p["node"], "protocol", p["label"], docs=p["source"])


class Adapter(Protocol):
    name: str

    def accepts(self, entity: Entity, ctx: Ctx) -> bool: ...

    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]: ...


def _short_call(result: CallResult) -> str:
    return result.signature.split(")(")[0] + ")"


def decimal_str(value: float | int, places: int = 6) -> str:
    """Contract decimal string (no exponent, no trailing zeros)."""
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
