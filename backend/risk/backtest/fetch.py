"""Download the price history the backtest replays (run once; the result is committed).

    python -m backend.risk.backtest.fetch            # writes backend/risk/backtest/data/history.json.gz

Sources (all public, no key):
- DefiLlama coins API: hourly USDe, sUSDe and every PT-sUSDe price on Ethereum (on-chain DEX pricing);
- Pendle API: hourly implied APY of every PT-sUSDe market (the input of the engine's PT formula);
- Binance spot klines: USDe/USDT hourly OHLC (a CEX venue: the Oct 10, 2025 low lives there, not on-chain);
- Chainlink USDe/USD (BASE_FEED_1 of the verified Morpho sUSDe/PYUSD oracle): every round of the current phase,
  read with getRoundData from latest state over public JSON-RPC (ETH_RPC_URL to override).

    python -m backend.risk.backtest.fetch --chainlink   # refresh only the Chainlink rounds in the existing file
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data" / "history.json.gz"

USDE = "ethereum:0x4c9EDD5852cd905f086C759E8383e09bff1E68B3"
SUSDE = "ethereum:0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"
START = datetime(2024, 2, 20, tzinfo=timezone.utc)
END = datetime(2026, 10, 10, tzinfo=timezone.utc)
HOUR = 3600
SPAN = 500  # DefiLlama points per request

# Pendle PT-sUSDe markets on Ethereum: (market, PT token, expiry), from api-v2.pendle.finance markets list.
PT_MARKETS = [
    ("0x107a2e3cd2bb9a32b9ee2e4d51143149f8367eba", "0xd810362556296c834e30c9a61d8e21a5cf29eab4", "2024-07-25"),
    ("0xd1d7d99764f8a52aff007b7831cc02748b2013b5", "0x6c9f097e044506712b58eac670c9a5fd4bccef13", "2024-09-26"),
    ("0xbbf399db59a845066aafce9ae55e68c505fa97b7", "0xae5099c39f023c91d3dd55244cafb36225b0850e", "2024-10-24"),
    ("0xa0ab94debb3cc9a7ea77f3205ba4ab23276fed08", "0xee9085fc268f6727d5d4293dbabccf901ffdcc29", "2024-12-26"),
    ("0xd3c29550d12a5234e6aeb5aea7c841134cd6ddd5", "0x386ae941d4262b0ee96354499df2ab8442734ec0", "2025-02-27"),
    ("0xcdd26eb5eb2ce0f203a84553853667ae69ca29ce", "0xe00bd3df25fb187d6abbb620b3dfd19839947b81", "2025-03-27"),
    ("0xb162b764044697cf03617c2efbcb1f42e31e4766", "0xb7de5dfcb74d25c2f21841fbd6230355c50d9308", "2025-05-29"),
    ("0x4339ffe2b7592dc783ed13cce310531ab366deac", "0x3b3fb9c57858ef816833dc91565efcd85d96f634", "2025-07-31"),
    ("0xa36b60a14a1a5247912584768c6e53e1a269a9f7", "0x9f56094c450763769ba0ea9fe2876070c0fd5f77", "2025-09-25"),
    ("0xb6ac3d5da138918ac4e84441e924a20daa60dbdd", "0xe6a934089bbee34f832060ce98848359883749b3", "2025-11-27"),
    ("0xed81f8ba2941c3979de2265c295748a6b6956567", "0xe8483517077afa11a9b07f849cee2552f040d7b2", "2026-02-05"),
    ("0x8dae8ece668cf80d348873f23d456448e8694883", "0x3de0ff76e8b528c092d47b9dac775931cef80f49", "2026-05-07"),
    ("0x177768caf9d0e036725a51d3f60d7e20f2d4d194", "0x5a19fa369f2895dcd8d2cee62e4ceae58ef92bbb", "2026-08-13"),
    ("0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e", "0xb195b618ea52b77cb2a58846f452f59f8dfa9390", "2026-11-26"),
]


def _get(url: str, retries: int = 4):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bsa-backtest"}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400:  # window outside the asset's history: no data
                return {}
            if attempt == retries - 1:
                raise RuntimeError(f"{url}: {e}") from e
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001  (network: retry, then fail loudly)
            if attempt == retries - 1:
                raise RuntimeError(f"{url}: {e}") from e
            time.sleep(2 * (attempt + 1))


def _hour(ts: float) -> int:
    return int(round(ts / HOUR)) * HOUR


def llama_hourly(coins: list[str], start: int, end: int) -> dict[str, dict[int, float]]:
    starts = list(range(start, end, SPAN * HOUR))
    url = "https://coins.llama.fi/chart/{}?start={}&span={}&period=1h"
    with ThreadPoolExecutor(8) as pool:
        pages = list(pool.map(lambda s: _get(url.format(",".join(coins), s, SPAN)), starts))
    out: dict[str, dict[int, float]] = {c: {} for c in coins}
    for page in pages:
        for coin, body in page.get("coins", {}).items():
            key = next(c for c in coins if c.lower() == coin.lower())
            for p in body["prices"]:
                out[key][_hour(p["timestamp"])] = p["price"]
    return out


def pendle_implied_apy(market: str, start: int, end: int) -> dict[int, float]:
    out: dict[int, float] = {}
    url = ("https://api-v2.pendle.finance/core/v2/1/markets/{}/historical-data?time_frame=hour"
           "&timestamp_start={}&timestamp_end={}")
    step = 50 * 24 * HOUR  # the API returns at most 1440 hourly rows per call
    for s in range(start, end, step):
        e = min(s + step, end)
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        for row in _get(url.format(market, iso(s), iso(e))).get("results", []):
            ts = int(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp())
            if row.get("impliedApy") is not None:
                out[_hour(ts)] = row["impliedApy"]
    return out


def binance_usde(start: int, end: int) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    url = "https://data-api.binance.vision/api/v3/klines?symbol=USDEUSDT&interval=1h&startTime={}&limit=1000"
    t = start
    while t < end:
        rows = _get(url.format(t * 1000))
        if not rows:
            break
        for k in rows:
            out[k[0] // 1000] = [float(k[1]), float(k[2]), float(k[3]), float(k[4])]  # open, high, low, close
        t = rows[-1][0] // 1000 + HOUR
    return out


CHAINLINK_USDE_USD = "0xa569d910839ae8865da8f8e70fffb0cba869f961"
RPC_URL = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
SEL_LATEST, SEL_ROUND = "0xfeaf968c", "0x9a6fc8f5"  # latestRoundData(), getRoundData(uint80)


def _eth_call(to: str, data: str) -> bytes | None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]})
    for attempt in range(4):
        try:
            req = urllib.request.Request(RPC_URL, data=body.encode(), headers={"content-type": "application/json",
                                                                               "User-Agent": "bsa-backtest"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            return None if "error" in out else bytes.fromhex(out["result"][2:])
        except Exception:  # noqa: BLE001
            time.sleep(1 + attempt)
    raise RuntimeError(f"eth_call {to} failed")


def chainlink_rounds(feed: str) -> list[list[float]]:
    """[updatedAt, answer] for every round of the feed's current phase (8 decimals)."""
    latest = _eth_call(feed, SEL_LATEST)
    round_id = int.from_bytes(latest[:32], "big")
    phase, last = round_id >> 64, round_id & ((1 << 64) - 1)

    def read(n: int):
        raw = _eth_call(feed, SEL_ROUND + ((phase << 64) | n).to_bytes(32, "big").hex())
        if not raw:
            return None
        answer = int.from_bytes(raw[32:64], "big", signed=True)
        updated = int.from_bytes(raw[96:128], "big")
        return [updated, answer / 1e8] if updated else None

    with ThreadPoolExecutor(8) as pool:
        rows = [r for r in pool.map(read, range(1, last + 1)) if r]
    return sorted(rows)


def main() -> None:
    if "--chainlink" in sys.argv:
        with gzip.open(DATA, "rt") as f:
            history = json.load(f)
        history["chainlink_usde_usd"] = chainlink_rounds(CHAINLINK_USDE_USD)
        history["sources"]["chainlink"] = f"Chainlink USDe/USD {CHAINLINK_USDE_USD} getRoundData (current phase)"
        with gzip.open(DATA, "wt") as f:
            json.dump(history, f, separators=(",", ":"))
        print(f"Chainlink USDe/USD: {len(history['chainlink_usde_usd'])} rounds -> {DATA}")
        return
    start, end = int(START.timestamp()), int(END.timestamp())
    base = {**llama_hourly([USDE], start, end), **llama_hourly([SUSDE], start, end)}
    pts = {}
    for market, token, expiry in PT_MARKETS:
        exp = int(datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc).timestamp())
        first = max(start, exp - 400 * 24 * HOUR)
        last = min(end, exp)
        apy = pendle_implied_apy(market, first, last)
        # A DefiLlama window that starts before the token existed is rejected: start at the market's first APY.
        prices = llama_hourly([f"ethereum:{token}"], min(apy, default=first), last)[f"ethereum:{token}"]
        pts[expiry] = {"market": market, "pt": token, "expiry": exp,
                       "price": {str(k): v for k, v in sorted(prices.items())},
                       "implied_apy": {str(k): v for k, v in sorted(apy.items())}}
        print(f"PT {expiry}: {len(prices)} prices, {len(apy)} APYs")
    binance = binance_usde(start, end)
    history = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {"onchain": "coins.llama.fi (hourly)", "pendle": "api-v2.pendle.finance historical-data (hourly)",
                    "binance": "data-api.binance.vision klines USDEUSDT 1h"},
        "usde": {str(k): v for k, v in sorted(base[USDE].items())},
        "susde": {str(k): v for k, v in sorted(base[SUSDE].items())},
        "pt": pts,
        "binance_usde_ohlc": {str(k): v for k, v in sorted(binance.items())},
        "chainlink_usde_usd": chainlink_rounds(CHAINLINK_USDE_USD),
    }
    history["sources"]["chainlink"] = f"Chainlink USDe/USD {CHAINLINK_USDE_USD} getRoundData (current phase)"
    DATA.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DATA, "wt") as f:
        json.dump(history, f, separators=(",", ":"))
    print(f"USDe {len(base[USDE])} h, sUSDe {len(base[SUSDE])} h, Binance {len(binance)} h -> {DATA}")


if __name__ == "__main__":
    main()
