"""Minimal read-only Ethereum client: eth_call with hand-encoded ABI for the few calls discovery needs.

Standard library only (no web3 dependency). Every read is pinned to one block so a snapshot is
reproducible. RPC endpoint: env ETH_RPC_URL, default a public node. Read-only: never signs.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

RPC_URL = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")

# keccak256(signature)[:4]; precomputed so no keccak implementation is needed at runtime.
SELECTORS = {
    "market(bytes32)": "5c60e39a",
    "idToMarketParams(bytes32)": "2c3c9157",
    "price()": "a035b1fe",
    "BASE_VAULT()": "eaa2d7b4",
    "BASE_FEED_1()": "f50a4718",
    "BASE_FEED_2()": "dc53858c",
    "QUOTE_VAULT()": "2e6f20a6",
    "QUOTE_FEED_1()": "56095e11",
    "QUOTE_FEED_2()": "acfbd39e",
    "description()": "7284e416",
    "decimals()": "313ce567",
    "latestRoundData()": "feaf968c",
    "symbol()": "95d89b41",
    "convertToAssets(uint256)": "07a2d13a",
}
ZERO_ADDRESS = "0x" + "0" * 40


def post_json(url: str, payload: dict, timeout: float = 30) -> dict:
    # Public endpoints reject urllib's default user agent.
    headers = {"content-type": "application/json", "user-agent": "defi-contagion-discovery/0.1"}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def rpc(method: str, params: list) -> object:
    body = post_json(RPC_URL, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


@dataclass(frozen=True)
class Block:
    number: int
    timestamp: int


def latest_block() -> Block:
    block = rpc("eth_getBlockByNumber", ["latest", False])
    return Block(int(block["number"], 16), int(block["timestamp"], 16))


def call(to: str, signature: str, *args: bytes, block: int | None = None) -> bytes:
    data = "0x" + SELECTORS[signature] + "".join(a.hex() for a in args)
    tag = hex(block) if block is not None else "latest"
    return bytes.fromhex(str(rpc("eth_call", [{"to": to, "data": data}, tag]))[2:])


# --- ABI helpers (static types + one dynamic string) ------------------------------------

def word(raw: bytes, index: int) -> bytes:
    return raw[32 * index: 32 * (index + 1)]


def as_uint(raw: bytes, index: int = 0) -> int:
    return int.from_bytes(word(raw, index), "big")


def as_int(raw: bytes, index: int = 0) -> int:
    return int.from_bytes(word(raw, index), "big", signed=True)


def as_address(raw: bytes, index: int = 0) -> str:
    return "0x" + word(raw, index)[12:].hex()


def as_string(raw: bytes) -> str:
    offset = as_uint(raw, 0)
    length = int.from_bytes(raw[offset: offset + 32], "big")
    return raw[offset + 32: offset + 32 + length].decode()


def uint_arg(value: int) -> bytes:
    return value.to_bytes(32, "big")


def bytes32_arg(hex_id: str) -> bytes:
    return bytes.fromhex(hex_id.removeprefix("0x").rjust(64, "0"))


# --- common reads ---------------------------------------------------------------------

def erc20(address: str, block: int) -> tuple[str, int]:
    return as_string(call(address, "symbol()", block=block)), as_uint(call(address, "decimals()", block=block))


def feed(address: str, block: int) -> dict:
    """Chainlink-style feed: description, answer, seconds since update (at `block`)."""
    decimals = as_uint(call(address, "decimals()", block=block))
    round_data = call(address, "latestRoundData()", block=block)
    return {
        "address": address,
        "description": as_string(call(address, "description()", block=block)),
        "answer": as_int(round_data, 1) / 10 ** decimals,
        "updated_at": as_uint(round_data, 3),
    }
