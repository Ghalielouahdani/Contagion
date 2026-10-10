import json

import httpx
import pytest
from eth_abi import encode

from backend.adapters.sources import (
    Cassette,
    CallReverted,
    EvmClient,
    HttpJson,
    ReplayMiss,
    SourceError,
    _split_types,
)


def test_split_types_handles_tuples():
    assert _split_types("address,(address,uint256),uint8[]") == ["address", "(address,uint256)", "uint8[]"]
    assert _split_types("") == []


def _rpc_transport(result_for):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], **result_for(payload)})

    return httpx.MockTransport(handler)


def test_call_encodes_decodes_and_lowercases_addresses():
    answer = "0x" + encode(["address", "uint256"], ["0xAbCdEf0000000000000000000000000000000001", 7]).hex()
    evm = EvmClient(Cassette(), urls=("http://rpc",), transport=_rpc_transport(lambda p: {"result": answer}))
    evm.pin(100)
    res = evm.call("0x1111111111111111111111111111111111111111", "f(uint256)(address,uint256)", 5)
    assert res.values == ("0xabcdef0000000000000000000000000000000001", 7)
    assert res.block == 100


def test_revert_is_cached_and_reported():
    calls = []

    def result_for(payload):
        calls.append(payload)
        return {"error": {"code": 3, "message": "execution reverted"}}

    evm = EvmClient(Cassette(), urls=("http://rpc",), transport=_rpc_transport(result_for))
    assert evm.try_call("0x1111111111111111111111111111111111111111", "g()(uint256)") is None
    with pytest.raises(CallReverted):
        evm.call("0x1111111111111111111111111111111111111111", "g()(uint256)")
    assert len(calls) == 1  # second answer came from the cassette


def test_network_failure_becomes_source_error():
    def handler(request):
        raise httpx.ConnectError("down")

    evm = EvmClient(
        Cassette(), urls=("http://a", "http://b"), transport=httpx.MockTransport(handler), retries=2, backoff=0
    )
    with pytest.raises(SourceError, match="every RPC endpoint"):
        evm.latest_block()


def test_http_rate_limit_is_retried_then_succeeds():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(429) if len(attempts) < 2 else httpx.Response(200, json={"ok": True})

    http = HttpJson(Cassette(), transport=httpx.MockTransport(handler), retries=3, backoff=0)
    assert http.get("http://api/x") == {"ok": True}
    assert len(attempts) == 2


def test_replay_never_reaches_the_network(tmp_path):
    path = tmp_path / "c.json"
    live = Cassette("live", path)
    live.put(Cassette.key("rpc", ["eth_chainId", []]), "0x1")
    live.save({"block": 1, "observed_at": "2026-01-01T00:00:00Z"})

    def handler(request):
        raise AssertionError("network used in replay mode")

    evm = EvmClient(Cassette("replay", path), urls=("http://rpc",), transport=httpx.MockTransport(handler))
    assert evm.chain_id() == 1
    with pytest.raises(ReplayMiss):
        evm.latest_block()


def test_long_cassette_keys_are_hashed_but_unique():
    a = Cassette.key("rpc", ["eth_call", ["x" * 1000]])
    b = Cassette.key("rpc", ["eth_call", ["x" * 999 + "y"]])
    assert a != b and len(a) < 250
