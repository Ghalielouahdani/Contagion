# backend/risk/ — owner: P2 (Quantitative Risk & Propagation)

The risk engine. It takes a scenario and computes what happens to each position and to the whole portfolio.

```
portfolio + dependency_graph + market_snapshot + scenario_request  ──►  risk_result.json
```

Read: blueprint sections 7 (all of it: formulas), 4.2 (conventions), 11.4–11.7 (inputs and golden outputs), 16 P2.

## What to do, step by step

1. **Valuation layer (before any shock):** compute each position's mark value from the snapshot.
   - sUSDe = shares × exchange_rate × USDe price
   - PT = USDe price / (1 + implied_apy)^(days_to_maturity / 365)
   - borrow position: collateral value, debt value, net equity = collateral − debt
   Check: you must reproduce `portfolio.json` (gross $10.0m, debt $3.8m, net $6.2m).
2. **Scenario A — USDe depeg** (section 7.1):
   - shock the USDe market price; sUSDe moves by `susde_market_beta` × the shock;
   - **the oracle price ≠ the market price**: oracle move = `oracle_pass_through` × market move (per market from the snapshot, unless the request sets an override);
   - recompute Aave HF = collateral × LT / debt, and Morpho LTV = debt / collateral (oracle value);
   - return **distance to liquidation** (Aave: 1 − 1/HF; Morpho: 1 − LTV/LLTV), not just `liquidatable: true/false`;
   - PT: reprice with the shocked USDe price and implied APY + `pt_implied_apy_shock`;
   - `backing_impairment_pct` lowers the exchange rate. That is a separate mechanism from the market depeg; don't reuse the same %.
3. **Scenario B — liquidity crisis** (section 7.2):
   - mark value is unchanged; **executable value** = what a full sale would actually realize;
   - crisis depth = depth × (1 − reduction); haircut = size² / (depth + size);
   - position-level figures assume each position exits alone. The portfolio total uses a **joint exit per shared venue**, and the difference is reported as `shared_liquidity_penalty_usd`.
4. **Loss components:** `market_repricing`, `backing_impairment`, `liquidation_penalty` and `execution_haircut` must sum exactly to `conditional_loss_usd`. **No double counting**: a price drop and a later sale at that price are one loss, not two.
5. **Portfolio aggregation** uses net equity, never protocol TVL.

## Golden values to reproduce (section 11)

| Scenario  | Check |
|-----------|-------|
| Depeg -5% | Aave HF 1.4167 → 1.3458; Morpho LTV stays 0.6667 (pass-through 0); total loss 523,320.57 |
| Liquidity -80% | total loss 920,646.49, of which shared-venue penalty 251,015.13 |

## Required tests

No shock → no change. A bigger shock → a bigger loss (monotonic). Pass-through 0 vs 1. PT at and after maturity. The sum of positions reconciles with the portfolio total. The golden values above.

## Definition of done

Both scenarios run on the same portfolio, results are reproducible, and every loss and liquidation flag is explained. Never call a scenario loss an "expected loss": there is no probability at this stage.
