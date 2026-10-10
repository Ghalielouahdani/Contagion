# backend/discovery/ — owner: P1 (Data & Dependency Discovery)

Turns a portfolio into the two "facts" files the rest of the team uses:

```
portfolio.json ──► discover() ──► dependency_graph.json + market_snapshot.json
                      │
                      └── explorer: seeds from each position, then adapters (backend/adapters/)
                          breadth-first with a visited set and depth / size / time limits
```

Nothing in the graph is hand-written: the protocol entry points (Aave PoolAddressesProvider,
Morpho Blue, Pendle router, USDe/sUSDe/USDC… addresses) come from the issuers' published lists in
`backend/adapters/registry/ethereum.json`, and are re-checked on-chain at every run. Markets, PT/SY,
oracles, feeds, eMode categories, lending markets accepting a PT and exit routes are all discovered.

## Run it

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

# live: real Ethereum + Pendle/Morpho/KyberSwap APIs (public RPC by default, ETH_RPC_URL to override)
.venv/bin/python -m backend.discovery discover --portfolio backend/discovery/examples/live_ethena_01.json \
    --mode live --out /tmp/p1 --revalue

# replay: same pipeline, offline, from a recorded run (deterministic; what the tests use)
.venv/bin/python -m backend.discovery discover --portfolio backend/discovery/examples/live_ethena_01.json \
    --mode replay --cassette backend/discovery/cassettes/live_ethena_01.json --out /tmp/p1

# record a new frozen demo snapshot
.venv/bin/python -m backend.discovery discover --portfolio <portfolio.json> --mode live --record \
    --cassette backend/discovery/cassettes/<name>.json --out <dir>

# read the result
.venv/bin/python -m backend.discovery explain  --graph /tmp/p1/dependency_graph.json --position pendle_01
.venv/bin/python -m backend.discovery impacted --graph /tmp/p1/dependency_graph.json --node offchain:tether

.venv/bin/python -m pytest backend/discovery tests          # offline
DISCOVERY_LIVE=1 .venv/bin/python -m pytest backend/discovery/tests/test_live.py   # network
```

From Python (what the API layer calls):

```python
from backend.discovery import discover, impacted_by
graph, snapshot = discover(portfolio, mode="fixture" | "live" | "replay", cassette=path)
impacted_by(graph, "asset:USDe")   # positions + paths that depend on a component
```

| mode      | network | output                                                                 |
|-----------|---------|------------------------------------------------------------------------|
| `fixture` | no      | `contracts/fixtures/demo_ethena_01` graph + snapshot (golden, assumed) |
| `live`    | yes     | discovered now, every eth_call pinned to `latest - 3`                  |
| `replay`  | no      | the live pipeline answered from a cassette; a missing answer is an error |

All three return the same contract shape, validated against `contracts/schemas/v1` plus cross-file
checks (`validation.py`) before being returned.

## Examples (`examples/`, each with a recorded cassette)

| file | what it shows |
|------|---------------|
| `live_ethena_01.json` | the blueprint's 4 positions on real markets → `contracts/fixtures/live_ethena_01/` |
| `pendle_pt_holding.json` | PT-sUSDE-26NOV2026 held: layers 3 and 5 not applicable, lending markets accepting it listed as context |
| `pendle_pt_morpho_collateral.json` | the same PT deposited on Morpho: all five layers resolved |
| `morpho_susde_pyusd.json` | another sUSDe Morpho market: different oracle (USDe/USD feed, pass-through 1) → different graph |
| `pendle_pt_susds.json` | another Pendle market (sUSDS): no Ethena, issuer left **unresolved** instead of guessed |

USD values in the example portfolios are recomputed from the snapshot (`--revalue`); quantities are the fictional input.

## Output contract (additions to schema v1, all optional)

- graph: `chain_id`, `block_number`, `coverage` (per position, per layer: status, nodes, edges, note,
  context_nodes), `unresolved` (subject + reason), `discovery` (mode, limits, call counts, trace);
  evidence gains `call` (function or query) and `note` (why the edge exists).
- snapshot: `exit_venues.*.quotes` (executable quotes behind the depth), `markets.*.details`.
- vocabulary: relations `prices_debt_with`, `uses_feed`, `wraps`, `yield_generated_by`, `pools_asset`,
  `routes_through` (plus `holds`, `reads_price_of` from the risk-engine branch); channels `settlement`, `yield_source`.

Edge direction is the contract's: `A -> B` = A depends on B. Node ids stay readable (`asset:USDe`,
`market:<position_id>`, `offchain:ethena_backing`) because the risk engine keys on them; identity is the
`(chain_id, address)` in attributes, never the symbol.

## The five layers (challenge example), per position

| layer | how it is found | status today (live_ethena_01) |
|-------|-----------------|-------------------------------|
| settlement chain | `eth_chainId` + `eth_getCode` of every asset/market at the pinned block | verified |
| yield source & issuer | PT.SY() → SY.yieldToken() → sUSDe.asset(); USDe.minter() vs Ethena's published minter; sUSDe rewards vesting; off-chain backing from docs | documented (backing is off-chain) |
| oracle | the market names its oracle (Aave getSourceOfAsset, Morpho MarketParams.oracle); the oracle is opened recursively | verified for borrows, not_applicable for holdings |
| PT market & AMM / exit | Pendle readTokens/readState (implied rate, reserves, scalar root, fees); exit route quoted (Pendle router for PTs, KyberSwap otherwise) | verified |
| lending market (collateral) | Morpho/Aave market of the position; for PTs, a scan of Morpho markets and Aave reserves accepting the exact PT | verified for borrows, not_applicable (+ context) for holdings |

## What discovery found that the fixtures assumed

- **Aave prices USDe collateral with a capped USDT/USD feed** (and sUSDe with sUSDe-rate × USDT/USD):
  USDe pass-through 0, not 1, and a hidden USDT dependency (`impacted --node offchain:tether` → aave_01).
- **Morpho sUSDe/USDC reads only the sUSDe vault rate** (USDe hardcoded at 1): pass-through 0 is now observed.
  That market is tiny (≈3.9k USDC borrowed): the fictional 2m debt is flagged as impossible at that size.
- **The Morpho PT-sUSDE-26NOV2026/USDC market uses a meta-oracle**: a Pendle linear discount (6 %/yr, no
  market input) with a challengeable backup that multiplies by the USDe/USD feed.
- **sUSDe exit liquidity has a cliff**: 1.6m sUSDe → 0.09 % loss, 2.4m → 0.16 %, both at once (4.0m) → 12.9 %.
  The shared venue `venue:susde_usdc` therefore carries a quote curve; depth is calibrated on the joint size.

## Limits (visible, not hidden)

- One chain per run (Ethereum). Off-chain Ethena backing and custody are `documented`, never `verified`.
- Feed → asset links from a Chainlink description are `inferred` (symbol mapping to the registry).
- API data (Pendle, Morpho, KyberSwap) is time-stamped, not block-pinned; on-chain values are cross-checked
  against it and differences become warnings.
- `effective_depth_usd` turns one executable quote into the constant-product proxy P2/P3 use; read
  `quotes` when sizes differ from the joint size. Quotes are for the fictional sizes at `observed_at`.
- The sUSDe token APY comes from the Pendle API (7-day style figure), cross-checked against a short
  on-chain window (public RPCs refuse older state without an archive key).
- Tokens with no protocol adapter or registry entry (e.g. sUSDS, USDS) get their on-chain structure
  but an `unresolved` issuer/yield source.
