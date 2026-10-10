# Unified stress portfolio

`stress_portfolio_01` is the default portfolio for every scenario. Allocations are
synthetic, sized on real Ethereum markets; this is not a copied wallet or a claim
that these balances exist on-chain. The Morpho borrow targets 88% LTV, near the
observed 87.93% borrower concentration of the sUSDe/PYUSD market.

| Position | Allocation | Purpose |
|---|---|---|
| sUSDe holding | 400,000 shares, about $501k | Direct depeg, yield loss and shared exit liquidity |
| Aave v3 eMode 11 | 1m USDe collateral, 820k USDC debt | Leverage with a capped USDT oracle; USDe spot and liquidation can diverge |
| Morpho sUSDe/PYUSD borrow | 400k sUSDe collateral, about 440.6k PYUSD debt | 88% initial LTV versus 91.5% LLTV; mild depeg or 30-day funding squeeze triggers liquidation |
| Pendle PT-sUSDe, 26 November 2026 | 300k PT tokens, about $298k | Fixed-term exposure, discount-rate sensitivity and maturity carry |
| Morpho sUSDe/PYUSD supply | 1m PYUSD | Lender losses from observed borrower distribution; shares collateral exit venue with the borrow and holding |
| Morpho USDe/RLUSD supply | 500k RLUSD | Another lender and collateral route; contagion across USDe and sUSDe |

Gross exposure is $3,799,182.70, debt $1,260,546.79, equity $2,538,635.91 at the
recorded prices. Allocation sizes are below recorded Morpho supply/borrow totals.
They remain hypothetical positions, not additional debt injected into the real
market borrower distribution. The cascade uses that distribution once through
the lender market entries; the portfolio borrower is valued separately.

All seven scenarios use these same six positions. See the [scenario guide](risk_scenarios.md) for parameters, formulas and result interpretation. At the presets, the -5% depeg
liquidates the Morpho borrow, leaves Aave non-liquidatable, and creates no lender
bad debt. The 30-day carry squeeze also crosses the Morpho threshold. The cascade
adds forced-selling feedback and positive losses for both lenders. Do not sum
scenario losses: these are alternative stress cases, not cumulative events.

## Sources and limits

Inputs are composed from `verified_2026_10_10` and
`verified_lending_2026_10_10`. Their on-chain observations were recorded at blocks
26161879 and 26162896. The combined snapshot sets `block_number` to null and warns
that it is a composed historical snapshot, not a single-block live observation.
Graph edges retain their original evidence, observation times and confidence.
Latest recorded values take precedence for shared prices and executable quotes;
position USD marks are recomputed from the resulting prices.

See [verified markets](verified_markets.md). Quotes represent recorded routing
conditions; PT pricing uses an approximation, and off-chain backing links are
documented rather than verified. Missing lender withdrawal fees/gas remain
explicit warnings. The current generic live-discovery service does not support
`lending_supply`; use stored inputs for this portfolio until that adapter is added.

## Rebuild and run

From the repository root:

```bash
.venv/bin/python -m backend.discovery.build_stress_portfolio
.venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

API mode is the default: every run recomputes risk and P3 decisions using the
selected parameters. The UI shows only this portfolio. Archived development sets
remain available through explicit `VITE_FIXTURE_SET` overrides and API `?set=` for
regression checks. Recorded-results mode uses generated engine surfaces; missing
data raises an error and never fabricates a risk result or execution decision.
