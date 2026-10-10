"""Data sources used by the adapters: an EVM JSON-RPC client and a JSON HTTP client.

Both go through a Cassette so a live run can be recorded and replayed offline:
- live:   real network calls (optionally recorded);
- replay: answers come only from a recorded cassette; a missing answer is an error, never a guess.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from eth_abi import decode, encode
from eth_utils import keccak

DEFAULT_RPC_URLS = ("https://ethereum-rpc.publicnode.com", "https://eth.drpc.org")
MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"  # same address on every EVM chain (mds1/multicall)
USER_AGENT = "defi-contagion-discovery/0.1 (read-only)"


class SourceError(Exception):
    """A data source could not answer (network, rate limit, missing replay entry)."""


class CallReverted(SourceError):
    """eth_call reverted or returned no data: the contract does not implement the function."""


class ReplayMiss(SourceError):
    """Replay mode and the request was never recorded."""


def _host(url: str) -> str:
    """Endpoint name safe to print: RPC keys often live in the URL path or query."""
    return urlsplit(url).netloc or "rpc"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Cassette:
    """Request -> response store. Keys are canonical JSON of the request."""

    def __init__(self, mode: str = "live", path: Path | None = None):
        if mode not in ("live", "replay"):
            raise ValueError(f"unknown cassette mode {mode!r}")
        self.mode = mode
        self.path = path
        self.entries: dict[str, Any] = {}
        self.meta: dict[str, Any] = {}
        if mode == "replay":
            if path is None or not path.exists():
                raise SourceError(f"replay mode needs an existing cassette, got {path}")
            raw = json.loads(path.read_text())
            self.meta, self.entries = raw["meta"], raw["entries"]

    @staticmethod
    def key(kind: str, request: Any) -> str:
        raw = json.dumps(request, sort_keys=True, separators=(",", ":"))
        if len(raw) > 400:  # e.g. multicall payloads: keep the file small, keys stay unique
            raw = raw[:120] + " sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        return kind + " " + raw

    def get(self, key: str) -> Any:
        if key in self.entries:
            return self.entries[key]
        if self.mode == "replay":
            raise ReplayMiss(f"not in cassette: {key[:160]}")
        return None

    def put(self, key: str, value: Any) -> None:
        self.entries[key] = value

    def save(self, meta: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.meta = meta
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"meta": meta, "entries": dict(sorted(self.entries.items()))}, indent=1) + "\n")


def _with_retries(fn, retries: int = 3, backoff: float = 0.8):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                break
            time.sleep(backoff * (2**attempt))
    status = getattr(getattr(last, "response", None), "status_code", None)
    reason = f"HTTP {status}" if status is not None else f"{type(last).__name__}: {last}"  # never echo the URL
    raise SourceError(f"request failed after {retries} attempts: {reason}") from last


_SIG = re.compile(r"^(\w+)\((.*?)\)(?:\((.*)\))?$")


def _split_types(types: str) -> list[str]:
    """Split 'address,(address,uint256),uint8[]' at top-level commas."""
    out, depth, cur = [], 0, ""
    for ch in types:
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    if cur:
        out.append(cur)
    return [t.strip() for t in out if t.strip()]


@dataclass
class CallResult:
    """One eth_call: what was asked, at which block, and the decoded answer."""

    to: str
    signature: str
    block: int | None
    values: tuple

    @property
    def value(self) -> Any:
        return self.values[0] if len(self.values) == 1 else self.values


class EvmClient:
    """Read-only Ethereum JSON-RPC client. Every eth_call is pinned to one block."""

    def __init__(
        self,
        cassette: Cassette,
        urls: tuple[str, ...] | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        retries: int = 3,
        backoff: float = 0.8,
    ):
        env = os.environ.get("ETH_RPC_URL")
        self.urls = urls or ((env,) if env else DEFAULT_RPC_URLS)
        self.cassette = cassette
        self.block: int | None = None
        self.retries, self.backoff = retries, backoff
        self._http = httpx.Client(timeout=timeout, headers={"user-agent": USER_AGENT}, transport=transport)
        self._id = 0
        self.calls = 0

    def _rpc(self, method: str, params: list, slim: Callable[[Any], Any] | None = None) -> Any:
        """slim reduces a result before it is cached (and returned), e.g. bytecode -> size + head."""
        key = Cassette.key("rpc" if slim is None else "rpc:slim", [method, params])
        cached = self.cassette.get(key)
        if cached is not None:
            if isinstance(cached, dict) and "error" in cached:
                raise CallReverted(cached["error"])
            return cached
        errors = []
        for url in self.urls:
            self._id += 1

            def send(url=url):
                r = self._http.post(url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
                r.raise_for_status()
                return r.json()

            try:
                body = _with_retries(send, self.retries, self.backoff)
            except SourceError as exc:
                errors.append(f"{_host(url)}: {exc}")
                continue
            self.calls += 1
            if "error" in body:
                message = str(body["error"].get("message", body["error"]))
                if method == "eth_call" and ("revert" in message.lower() or "invalid opcode" in message.lower()):
                    self.cassette.put(key, {"error": message})
                    raise CallReverted(message)
                errors.append(f"{_host(url)}: {message}")
                continue
            result = slim(body["result"]) if slim else body["result"]
            self.cassette.put(key, result)
            return result
        raise SourceError(f"{method} failed on every RPC endpoint: {errors}")

    # chain-level reads -------------------------------------------------------------------
    def chain_id(self) -> int:
        return int(self._rpc("eth_chainId", []), 16)

    def latest_block(self) -> int:
        return int(self._rpc("eth_blockNumber", []), 16)

    def gas_price(self) -> int:
        return int(self._rpc("eth_gasPrice", []), 16)

    def pin(self, block: int) -> None:
        self.block = block

    def block_timestamp(self, block: int) -> int:
        return int(self._rpc("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)

    def get_code(self, address: str) -> dict:
        """{'size': bytes of runtime code, 'head': first 45 bytes as hex} (enough to spot EIP-1167 proxies)."""
        return self._rpc(
            "eth_getCode",
            [address.lower(), self._tag()],
            slim=lambda code: {"size": (len(code) - 2) // 2 if code else 0, "head": (code or "0x")[:92]},
        )

    def _tag(self, block: int | None = None) -> str:
        b = block if block is not None else self.block
        return hex(b) if b is not None else "latest"

    # contract reads ----------------------------------------------------------------------
    def call(self, to: str, signature: str, *args: Any, block: int | None = None) -> CallResult:
        """signature = 'name(argTypes)(returnTypes)', e.g. 'balanceOf(address)(uint256)'."""
        m = _SIG.match(signature.replace(" ", ""))
        if not m:
            raise ValueError(f"bad signature {signature!r}")
        name, arg_types, ret_types = m.group(1), _split_types(m.group(2)), _split_types(m.group(3) or "")
        selector = keccak(text=f"{name}({','.join(arg_types)})")[:4]
        data = "0x" + (selector + encode(arg_types, list(args))).hex()
        tag = self._tag(block)
        raw = self._rpc("eth_call", [{"to": to.lower(), "data": data}, tag])
        payload = bytes.fromhex(raw[2:]) if raw and raw != "0x" else b""
        if not payload and ret_types:
            raise CallReverted(f"{signature} on {to}: empty return data")
        try:
            values = tuple(decode(ret_types, payload)) if ret_types else ()
        except Exception as exc:  # wrong ABI guess: treat as "not implemented"
            raise CallReverted(f"{signature} on {to}: undecodable return ({exc})") from exc
        values = tuple(v.lower() if isinstance(v, str) and v.startswith("0x") and len(v) == 42 else v for v in values)
        return CallResult(to.lower(), signature, int(tag, 16) if tag != "latest" else None, values)

    def try_call(self, to: str, signature: str, *args: Any, block: int | None = None) -> CallResult | None:
        try:
            return self.call(to, signature, *args, block=block)
        except CallReverted:
            return None

    def multicall(self, calls: list[tuple[str, str, tuple]]) -> list[CallResult | None]:
        """Many reads in one eth_call through Multicall3 (same block by construction). None = that call reverted."""
        encoded, shapes = [], []
        for to, signature, args in calls:
            m = _SIG.match(signature.replace(" ", ""))
            name, arg_types, ret_types = m.group(1), _split_types(m.group(2)), _split_types(m.group(3) or "")
            data = keccak(text=f"{name}({','.join(arg_types)})")[:4] + encode(arg_types, list(args))
            encoded.append((to.lower(), True, data))
            shapes.append((to.lower(), signature, ret_types))
        result = self.call(MULTICALL3, "aggregate3((address,bool,bytes)[])((bool,bytes)[])", encoded)
        out: list[CallResult | None] = []
        for (ok, payload), (to, signature, ret_types) in zip(result.value, shapes):
            if not ok or (ret_types and not payload):
                out.append(None)
                continue
            try:
                values = tuple(decode(ret_types, payload))
            except Exception:
                out.append(None)
                continue
            values = tuple(
                v.lower() if isinstance(v, str) and v.startswith("0x") and len(v) == 42 else v for v in values
            )
            out.append(CallResult(to, signature, result.block, values))
        return out


class HttpJson:
    """JSON over HTTP (protocol APIs) with retries and recording."""

    def __init__(
        self,
        cassette: Cassette,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        retries: int = 3,
        backoff: float = 0.8,
    ):
        self.cassette = cassette
        self.retries, self.backoff = retries, backoff
        self._http = httpx.Client(timeout=timeout, headers={"user-agent": USER_AGENT}, transport=transport)
        self.calls = 0

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        slim: Callable[[Any], Any] | None = None,
    ) -> Any:
        return self._request("GET", url, params=params, headers=headers, slim=slim)

    def post(self, url: str, body: dict, headers: dict | None = None) -> Any:
        return self._request("POST", url, body=body, headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        body: dict | None = None,
        headers: dict | None = None,
        slim: Callable[[Any], Any] | None = None,
    ) -> Any:
        """slim keeps only the fields the adapters read, so recorded cassettes stay small."""
        key = Cassette.key("http", [method, url, params or {}, body or {}])
        cached = self.cassette.get(key)
        if cached is not None:
            return cached

        def send():
            r = self._http.request(method, url, params=params, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

        result = _with_retries(send, self.retries, self.backoff)
        if slim is not None:
            result = slim(result)
        self.calls += 1
        self.cassette.put(key, result)
        return result
