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

## Run it

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # once, from the repo root
.venv/bin/python -m pytest backend/risk                          # golden + property tests
```

```python
from backend.risk import simulate
result = simulate(portfolio, market_snapshot, scenario_request, dependency_graph)  # contract dicts in, risk_result dict out
```

```python
from backend.risk.analytics import analyze
value = analyze(portfolio, market_snapshot, scenario_request)  # risk_analytics dict: money value for the fund
```

`analyze` returns a headline (NAV, scenario loss, USDe effective leverage, de-risking savings, liquidation protection, break-even probability) plus factor exposure, breaking points, targeted vs uniform de-risking and liquidation protection. See blueprint section 7.5 and `docs/risk_engine_plan.md`.

Code map: `model.py` (contract views) · `pricing.py` (market state, PT, oracle) · `metrics.py` (HF/LTV registry per market_kind) · `liquidity.py` (haircuts, joint exits) · `scenarios/` (one file per scenario + registry) · `report.py` (rounding that reconciles to the cent) · `engine.py` (entry point) · `graph.py` + `contagion.py` (contagion paths from the dependency graph, graph/valuation cross-check, hubs) · `analytics/` (exposure, breaking points, de-risking, liquidation protection, sensitivity tornado + grids, `analyze`). For a custom heatmap: `sensitivity.grid(portfolio, snapshot, request, x_param, xs, y_param, ys)` on model objects.

Scenarios: `usde_depeg` (A), `liquidity_crisis` (B), `combined_crisis` (C: A then exits queued behind liquidators' selling), `carry_squeeze` (D: rates over the horizon, days to liquidation), `governance_change` (E: threshold cut / oracle switch, then A), `node_shock` (F: shock any graph node). C–F return a `comparison` block (reference runs + `excess_loss_usd`). See `docs/risk_engine_plan.md`.

Add a scenario: new file in `scenarios/` decorated with `@scenario("<id>")`, plus its import in `scenarios/__init__.py` and its schema in `contracts/`. Add a lending protocol: one compute function + one `register(...)` line in `metrics.py`.

## Roadmap

Full plan, differentiators and progress checklist: [docs/risk_engine_plan.md](../../docs/risk_engine_plan.md).
