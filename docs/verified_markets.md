# Verified markets log — 10 October 2026

On-chain verification of every market, oracle and dependency used by the portfolio. Each value below was read with `eth_call` on Ethereum mainnet (chain id 1) through `https://ethereum-rpc.publicnode.com`.

- **Block:** 26161879 (2026-10-10, timestamp 1791633443). Some reads were taken a few blocks earlier, during the same session (from block 26161860).
- **Fixture set built from it:** `contracts/fixtures/verified_2026_10_10/`. The holdings are fictional; markets, oracles, parameters, prices and yields are observed.
- **Graph:** `dependency_graph.json` in that set. Each edge's `evidence.reference` names the exact call and result below.

## 1. Tokens (Ethena, stablecoins)

| Asset | Address | Check | Result |
|---|---|---|---|
| USDe | `0x4c9EDD5852cd905f086C759E8383e09bff1E68B3` | `symbol()`, `decimals()` | USDe, 18 |
| sUSDe | `0x9D39A5DE30e57443BfF2A8307A4256c8797A3497` | `symbol()`, `decimals()` | sUSDe, 18 |
| sUSDe → USDe | same | `asset()` | `0x4c9E…68B3` (USDe): **edge sUSDe `redeemable_for` USDe verified** |
| sUSDe rate | same | `convertToAssets(1e18)` | **1.252344** USDe per sUSDe |
| sUSDe cooldown | same | `cooldownDuration()` | 86 400 s (1 day) |
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | `symbol()`, `decimals()` | USDC, 6 |
| PYUSD | `0x6c3ea9036406852006290770BEdFcAbA0e23A0e8` | `symbol()` | PYUSD |

sUSDe yield: 4.85 % (Ethena API, 30-day average, `ethena.fi/api/yields/protocol-and-staking-yield`). Cross-check: 4.21 % realised over 180 days, from the sUSDe rate snapshot in the Aave adapter below.

## 2. Aave v3 Ethereum (core market)

| Item | Address / call | Result |
|---|---|---|
| PoolAddressesProvider | `0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e` | `getMarketId()` = "Aave Ethereum Market" |
| Pool | `getPool()` | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` |
| AaveOracle | `getPriceOracle()` | `0x54586bE62E3c3580375aE3723C145253060Ca0C2` |
| PoolDataProvider | `getPoolDataProvider()` | `0x0a16f2FCC0D44FaE41cc54e079281D84A363bECD` |
| USDe, base mode | `getReserveConfigurationData(USDe)` | **LTV 0**, LT 0.75, bonus 8.5 %: no new borrowing against USDe outside eMode |
| USDe eMode | Pool `getEModeCategory*(11)` | **eMode 11 "USDe Stablecoin": LTV 0.90, LT 0.93, bonus 2.0 %**, USDe collateral (reserve id 30), USDC borrowable (reserve id 3) |
| USDe price source | AaveOracle `getSourceOfAsset(USDe)` | `0xC26D4a1c46d884cfF6dE9800B6aE7A8Cf48B4Ff8`, `description()` = **"Capped USDT/USD"** |
| underlying feed | `ASSET_TO_USD_AGGREGATOR()` | `0x3E7d1eAB13ad0104d2750B8863b489D65364e32D` "USDT / USD" = 0.999055 |
| sUSDe price source | `getSourceOfAsset(sUSDe)` | `0x42bc86f2f08419280a99d8fbEa4672e7c30a86ec` "Capped sUSDe / USDT / USD" (sUSDe rate × USDT/USD) |
| Rates | `getReserveData` | USDe supply 0.24 %, USDC variable borrow 4.65 % |

## 3. Morpho Blue

Morpho Blue: `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`. Markets listed via `api.morpho.org/graphql`, then each one checked with `idToMarketParams(id)` and `market(id)`.

| Market | Loan | LLTV | Size | Oracle (decoded on-chain) |
|---|---|---|---|---|
| **`0x90ef0c5a…c0d5` (used)** | PYUSD | 0.915 | 109.0 m supplied, 97.0 m borrowed | `0xE6212D05cB5aF3C821Fef1C1A233a678724F9E7E`: `BASE_VAULT` = sUSDe, `BASE_FEED_1` = `0xa569…F961` **"USDe / USD"**, `QUOTE_FEED_1` = `0x8f1d…8FB1` "PYUSD / USD" |
| `0x85c7f437…fcab` | USDC | 0.915 | **9.5 k supplied** | `0x873CD44b860DEDFe139f93e12A4AcCa0926Ffb87`: sUSDe vault only, no feeds (USDe hardcoded at 1 USD) |

Full ids: `0x90ef0c5a0dc7c4de4ad4585002d44e9d411d212d2f6258e94948beecf8b4c0d5` and `0x85c7f4374f3a403b36d54cc284983b2b02bbd8581ee0f3c36494447b87d9fcab`.

PYUSD borrow APY 4.18 % (Morpho API). Liquidation incentive 2.62 %, derived from the Morpho Blue formula min(1.15, 1 / (0.3 × LLTV + 0.7)) − 1.

## 4. Pendle

| Item | Address / call | Result |
|---|---|---|
| Market | `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e` | the only active sUSDe market (Pendle API `markets/active`) |
| `readTokens()` | SY / PT / YT | `0xBF98…5D02` SY-sUSDE, `0xB195…9390` **PT-sUSDE-26NOV2026**, `0x89E6…4E44` YT |
| `expiry()` | | 2026-11-26 00:00 UTC (46.5 days), equal to `PT.expiry()` |
| `SY.yieldToken()` | | sUSDe: **edge PT `redeemable_for` sUSDe verified** |
| Implied APY / liquidity | Pendle API | 5.01 %, **3.82 m USD liquidity** |

## 5. Chainlink feeds (freshness at the block)

| Feed | Address | Value | Last update |
|---|---|---|---|
| USDe / USD | `0xa569d910839Ae8865Da8F8e70FfFb0cBA869F961` | 0.999597 | 8.0 h before |
| PYUSD / USD | `0x8f1dF6D7F2db73eECE86a18b4381F4707b918FB1` | 1.000067 | 16.1 h before |
| USDT / USD | `0x3E7d1eAB13ad0104d2750B8863b489D65364e32D` | 0.999055 | 21.3 h before |

The feeds update on a deviation threshold or a heartbeat, not continuously. That is the real-world basis of the `oracle_lag_hours` parameter.

## Findings that change the demo

1. **Aave does not see a USDe depeg.** It prices USDe with the USDT/USD feed, so `oracle_pass_through` is 0. The demo fixture assumed 1.
   - **Aave cannot be liquidated by a USDe depeg, a USDe backing loss or a sUSDe rate cut.**
   - **It is exposed to a USDT depeg instead.** The graph shows it (`oracle:aave_01_usde → asset:USDT`), but the engine does not model a USDT factor yet.
2. **The liquid Morpho market does see it.** sUSDe/PYUSD reads Chainlink USDe/USD, so pass-through is 1: **liquidation at a 27.2 % depeg**. The demo fixture had the two protocols the other way round.
3. **The Morpho sUSDe/USDC market is unusable**: 9.5 k of liquidity against a 2 m borrow. The position moved to sUSDe/PYUSD.
4. **Aave needs eMode.** USDe has LTV 0 in base mode, and eMode 11 sets LT 0.93 and bonus 2 % (the fixture had 0.85 and 5 %).
5. **The PT position is 52 % of its Pendle pool** (2 m against 3.82 m of liquidity). An exit in stress is very costly. The constant-product proxy overstates the impact, because the Pendle AMM concentrates liquidity, but the size problem is real.
6. **The sUSDe cooldown is 1 day**, not 7.

## Still to verify (for P1)

- **Exit depth for the sUSDe and USDe routes**: still `assumed` proxies (200 m and 300 m). Replace them with aggregator quotes for 1–3 m sizes.
- **Pendle exit**: replace the constant-product proxy with a Pendle router quote.
- **Ethena issuance and backing edges**: documented, not observable on-chain (expected).
- **Re-run the checks** at the demo block: rates, prices and implied APY move.

To reproduce: every row above is a single `eth_call` with the function signature shown. Any web3 library and a public RPC endpoint are enough.

---

# P1 discovery snapshot — separate dataset

Proof behind every `verified: true` in `contracts/fixtures/live_ethena_01/`. Ethereum mainnet
(chain 1), every on-chain value read at **block 26162114** (2026-10-10T12:44:23Z); APIs read at
2026-10-10T12:45:15Z. Regenerate offline with the replay command in `backend/discovery/README.md`;
rerun live to refresh. Holdings are fictional; everything below is real.

## Markets used by the blueprint portfolio

| position | protocol | market id / address | key parameters | oracle (what it reads) | source |
|---|---|---|---|---|---|
| `aave_01` | Aave v3 "Aave Ethereum Market" | PoolAddressesProvider `0x2f39d218133afab8f2b819b1066c7e434ad94e9e`, Pool `0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2`, eMode **11 "USDe Stablecoin"** | USDe collateral / USDC debt; eMode LTV 0.90, LT **0.93**, bonus 2 %; outside eMode USDe has LTV 0 (LT 0.75) | `0xc26d4a1c46d884cff6de9800b6ae7a8cf48b4ff8` "Capped USDT/USD" → Chainlink USDT/USD `0x3e7d1eab…` → **USDe pass-through 0**, depends on USDT | getPool, getReservesList, getReserveConfigurationData, eMode bitmaps, getSourceOfAsset |
| `morpho_01` | Morpho Blue `0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb` | `0x85c7f4374f3a403b36d54cc284983b2b02bbd8581ee0f3c36494447b87d9fcab` | sUSDe / USDC, LLTV **0.915**, incentive 2.62 % (Morpho formula), IRM `0x870ac11d…`; ≈9.5k USDC supplied, ≈3.9k borrowed | `0x873cd44b860dedfe139f93e12a4acca0926ffb87` MorphoChainlinkOracleV2, BASE_VAULT = sUSDe, **no feed** → USDe hardcoded at 1, pass-through 0 | idToMarketParams, market, borrowRateView, Morpho API cross-check |
| `pendle_01` | Pendle | market `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e` | PT-sUSDE-26NOV2026 `0xb195b618…`, SY-sUSDE `0xbf984804…`, YT `0x89e6e5f7…`; expiry 2026-11-26; implied APY 5.011 % (`exp(lastLnImpliedRate) − 1`, matches API); liquidity ≈3.82m USD | none on a holding's path | readTokens, readState, PT.SY(), SY.yieldToken(), Pendle API |
| `ethena_susde_01` | Ethena | sUSDe `0x9d39a5de30e57443bff2a8307a4256c8797a3497`, USDe `0x4c9edd5852cd905f086c759e8383e09bff1e68b3` | 1 sUSDe = 1.25235 USDe; cooldown 24 h; minter = `0xe3490297…` as published by Ethena | — | asset(), convertToAssets, cooldownDuration, vestingAmount, minter(); docs.ethena.fi key addresses |

## Lending markets accepting the PT (layer 5 scan)

| market | parameters | oracle |
|---|---|---|
| Morpho `0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05` PT-sUSDE-26NOV2026 / USDC | LLTV 0.915; ≈7.93m USD collateral, utilization 90 % | meta-oracle `0xf8b29e7e…` (EIP-1167 clone): primary `0x8fca98c9…` = Pendle linear discount `0xa572dad7…` (6 %/yr, maturity 2026-11-26, no market input) → pass-through 0; backup `0xe2f4cfe0…` = discount × Chainlink USDe/USD → pass-through 1; switch only after a challenge (deviation > 0.75 %) |
| Aave v3 Ethereum Market | PT-sUSDE-26NOV2026 **not listed** (67 reserves checked) | — |

## Prices and exit routes in the snapshot

| item | value | source |
|---|---|---|
| USDe / USD | 0.99959682 | Chainlink `0xa569d910…` (observed) |
| USDC / USD | 0.9998651 | Chainlink `0x8fffffd4…` (observed) |
| sUSDe | 1.2518 | exchange rate × USDe (derived) |
| PT-sUSDE-26NOV2026 | 0.99339 | USDe / (1 + implied APY)^(days/365) (derived) |
| `venue:usde_usdc` | 3.0m USDe → 0.043 % loss | KyberSwap quote |
| `venue:susde_usdc` | 1.6m → 0.09 %, 2.4m → 0.16 %, **4.0m (joint) → 12.9 %** | KyberSwap quotes |
| `venue:pendle_pt_susde` | 2.08m PT → 0.15 % loss | Pendle router (`/v2/sdk/1/convert`) |

## Second example markets (prove the graph is not hardcoded)

| example | market | result |
|---|---|---|
| `morpho_susde_pyusd` | Morpho `0x90ef0c5a0dc7c4de4ad4585002d44e9d411d212d2f6258e94948beecf8b4c0d5` sUSDe/PYUSD, LLTV 0.915 | oracle `0xe6212d05…` = sUSDe vault × Chainlink USDe/USD ÷ PYUSD/USD → pass-through **1** |
| `pendle_pt_susds` | Pendle `0x9c560ebaf78e596cbcc27411d633a74d628dd7dc` PT-sUSDS-26NOV2026 | sUSDS → USDS verified as ERC-4626; issuer/yield source unresolved (no adapter); three Morpho markets accept the PT |

## 6. Lending markets: the real borrowers (verified_lending_2026_10_10)

Built by `backend/discovery/build_lending_set.py` (block 26162896). Market parameters and totals come from on-chain calls. Every borrower position comes from the Morpho indexer, valued at the oracle price read on-chain.

| Market | Supply / borrow | Oracle | Borrowers | Debt by oracle LTV (LLTV 0.915) |
|---|---|---|---|---|
| sUSDe / PYUSD `0x90ef…c0d5` | 109.0m / 97.0m | sUSDe vault × Chainlink USDe/USD ÷ PYUSD/USD (pass-through 1) | 31, 100.0% of on-chain debt indexed | 69% at 0.879, 31% at 0.850 |
| USDe / RLUSD `0xd9d2…14bf` | 50.0m / 45.7m | Chainlink USDe/USD ÷ RLUSD/USD (pass-through 1) | 10, 100.0% indexed | 90% at 0.883 |

These borrowers are loopers: an oracle drop of roughly 3.5 to 4% makes most of the debt liquidatable.

## 7. Exit liquidity at liquidation sizes

KyberSwap executable quotes (`backend/discovery/exit_quotes.py`), all-in loss versus the oracle price:

| Sell | 2m | 5m | 10m | 25m | 50m | 100m |
|---|---|---|---|---|---|---|
| USDe → USDC | 0.0% | 0.05% | **24.2%** | 77.2% | 89.9% | 94.7% |
| sUSDe → USDC | 0.07% | **13.1%** | 57.4% | 88.1% | 94.6% | 97.7% |

USDT as the output gives the same cliff. On-chain liquidity covers a few million; the loopers above hold more than 140m of debt against this collateral. In a depeg, permissionless liquidators sell into this curve; Ethena's direct redemption is reserved to whitelisted minters, and sUSDe has a 1-day cooldown.

Consequence in the engine (scenario G, liquidation cascade, verified lending set): a -5% USDe depeg liquidates 110.7m in round 1. The forced selling then crushes sUSDe to -70%, liquidates 32m more, and leaves **31.7m of bad debt** across both markets. Our fictional 8m of supply loses **1.48m**.

The same curves now price the exits of `verified_2026_10_10`; until then they were assumed depths of 200m and 300m.
