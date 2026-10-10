# backend/adapters/ — owner: P1 (Data & Dependency Discovery)

One adapter per protocol: **Ethena, Aave, Morpho, Pendle**. For one position, an adapter reads the real Ethereum contracts and protocol APIs, then returns:
- the **graph pieces**: nodes (asset, market, oracle, venue…) and edges (`issued_by`, `prices_collateral_with`, `exits_via`…), each with evidence;
- the **market parameters** that P2/P3 need (thresholds, oracle type, yields, maturity…).

The discovery service (`backend/discovery/`) calls the adapters and assembles their output.

Read: blueprint sections 6 (what "automatic" means), 11.2–11.3 (target output), 14 (risks), 16 P1.

## What to do, step by step

1. **Define a common interface.** For example `discover(position) -> nodes, edges, market_params, warnings`. All four adapters return the same shape.
2. **Find and verify the real markets** (the first task at kickoff; nobody else can do it):
   - Aave: a live market with USDe as collateral (check eMode).
   - Morpho: a live sUSDe/USDC market. Write down the market ID, **oracle address and oracle type**, and the LLTV.
   - Pendle: a live PT-sUSDe market. Write down the market address, PT token and maturity.
   - Ethena: the USDe and sUSDe contracts and the sUSDe → USDe exchange rate.
   Replace the `TO_VERIFY_...` placeholders in `portfolio.json` / `market_snapshot.json` with these values.
3. **Write each adapter:**
   - **Ethena:** read the sUSDe exchange rate on-chain. Add documented-only edges for the off-chain backing (custody, exchanges), marked `documented`.
   - **Aave:** read the liquidation threshold, liquidation bonus, oracle address, and supply/borrow APYs.
   - **Morpho:** read the market params (collateral, loan, oracle, IRM, LLTV) and the borrow APY. **Determine whether the oracle follows the USDe market price** (pass-through 1) or only the exchange rate (pass-through 0). This drives the demo story.
   - **Pendle:** read the PT, SY, underlying, maturity, implied APY, and pool liquidity.
4. **Attach evidence to every edge:** `method` (onchain_call, protocol_api, protocol_documentation), `reference` (contract address or URL), `observed_at`, `status`, and `confidence`.
5. **Normalize units:** token decimals (USDC has 6, most others 18), shares vs. assets for sUSDe, USD prices.

## Definition of done

- Each adapter works on at least one verified market and has unit tests (a fixture mode with recorded responses works offline).
- Two different market IDs produce two **different** graphs. Nothing is hardcoded as the final answer.
- A missing field becomes a warning plus `null`, never an invented value.

## Pitfalls

- An oracle price is not the spot price. Record which oracle each market uses.
- TVL is not exposure.
- RPC endpoints are read-only. Never ask for private keys.
