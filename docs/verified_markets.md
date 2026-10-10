# Verified-market log (P1)

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
