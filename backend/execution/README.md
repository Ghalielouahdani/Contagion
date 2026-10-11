# backend/execution/ — owner: P3 (Decision, Liquidity & Exit Optimization)

> **Concept, inputs, expected output and a real worked example (in French): [CONCEPT.md](CONCEPT.md).**

The decision engine. It answers: **"should I stay, reduce or exit this position, and is the exit worth what it costs?"**

```
portfolio + market_snapshot + risk_result + scenario_request  ──►  decision_result.json
```

Read: blueprint sections 8 (objective, break-even, recommendation rules), 7.2 (exit-cost proxy), 4.2 (conventions), 11.8 (golden output), 16 P3.

## What to do, step by step

1. **Five options per position:** exit 0%, 25%, 50%, 75% or 100%. Decisions are per position in v1. Exits happen **before** the shock, at pre-shock prices and with normal (pre-crisis) depth.
2. **Exit cost of each option** = fees + gas + price impact.
   - Token / PT: sell x × quantity on the position's exit venue.
   - Borrow position: pro-rata unwind. Withdraw x × collateral, sell it, repay x × debt.
   - Price impact: use the best available quote, in priority order executable → pool reserves → proxy (size² / (depth + size)). Set `quote_status` accordingly.
3. **Residual loss** = (1 − x) × the position's `conditional_loss_usd` from risk_result.
4. **Foregone yield** = x × carry over the horizon. Carry = collateral or token APY × value − borrow APY × debt, using `market_snapshot.yields`. Cash earns 0.
5. **Break-even probability** of each option vs staying:
   p*(x) = (ExitCost(x) + ForegoneYield(x)) / (ResidualLoss(0) − ResidualLoss(x))
   In plain terms: "if you think this scenario has more than p* chance of happening, this option is worth it."
6. **Recommendation** (section 8 rules):
   - no probability given → `INSUFFICIENT_DATA` plus the full table and every p*, never a fake "optimal" trade;
   - probability given and real quotes available → minimize J(x) = cost + p × residual + foregone yield; x = 0 → STAY, 0 < x < 1 → REDUCE, x = 1 → EXIT;
   - only proxy quotes available → show the result but flag it.

## Golden values (aave_01, depeg)

Full exit costs 32,742.97 and has a break-even probability of 22.48%. A 25% exit costs 2,660.32 and has a break-even probability of 7.75%. Reproduce all five rows of section 11.8.

## Required tests

0% exit costs 0. A bigger exit costs more (convex). No incident → STAY. The recommendation moves sensibly when the probability or the slippage changes. A case where a partial exit wins. The golden values.

## Pitfalls

- Never compare a certain cost with an unweighted scenario loss as if the scenario were certain.
- Use the same horizon for costs, losses and yield.

---

# Implementation (P3, delivered)

Everything above is the original brief and is kept as is. This part documents what the module actually does.

## Module layout

```
backend/execution/
├── entrypoint.py    handle_decide_request(): the single entry point for POST /api/v1/decide
├── decision.py      decision engine: decide_position(), decide_portfolio(), load_contracts()
├── exit_cost.py     pluggable exit-cost estimator (executable → pool_reserves → proxy)
├── sensitivity.py   data for the dashboard slider: J(x) vs probability, p* vs pool depth
├── tests/           pytest suite (59 tests)
└── JOURNAL_P3.md    step-by-step build log (French)
```

Standard library only (`decimal`, `json`, `pathlib`, `dataclasses`); `pytest` for tests.

## Entry point for P4: `POST /api/v1/decide`

```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from backend.execution.entrypoint import handle_decide_request

app = FastAPI()

@app.post("/api/v1/decide")
def decide(request: dict):
    status, body = handle_decide_request(request)
    return JSONResponse(body, status_code=status)
```

`handle_decide_request(request) -> (http_status, body)` never raises.

### Request

| Field            | Required | Meaning |
|------------------|----------|---------|
| `schema_version` | yes      | must be `"1.0"` |
| `portfolio_id`   | yes      | must match the portfolio used |
| `position_id`    | yes      | e.g. `"aave_01"` |
| `scenario_id`    | fixture mode | `"usde_depeg"` or `"liquidity_crisis"` (selects the fixture files) |
| `probability`    | no       | user-supplied scenario probability as a decimal string (`"0.15"`) or `null`. Overrides `scenario_request.assumptions.probability`. Never estimated by P3. |
| `include`        | no       | any of `"sensitivity"`, `"portfolio_summary"` |
| `inputs`         | live mode | `{portfolio, market_snapshot, risk_result, scenario_request}` from P1/P2. If absent, the `demo_ethena_01` fixtures are used. |

```json
{
  "schema_version": "1.0",
  "portfolio_id": "demo_ethena_01",
  "position_id": "aave_01",
  "scenario_id": "usde_depeg",
  "probability": "0.15"
}
```

### Response (200)

`decision` is a `decision_result` (schema v1, section 11.8). `sensitivity` and `portfolio_summary` are added when requested.

```json
{
  "status": "ok",
  "mode": "fixture",
  "decision": {
    "schema_version": "1.0",
    "decision_id": "decision_sim_001",
    "simulation_id": "result_sim_001",
    "portfolio_id": "demo_ethena_01",
    "position_id": "aave_01",
    "scenario_id": "usde_depeg",
    "horizon_days": 7,
    "mode": "expected_cost",
    "currency": "USD",
    "exit_options": [
      { "exit_fraction": "0.00", "fees_usd": "0", "gas_usd": "0", "price_impact_usd": "0", "estimated_exit_cost_usd": "0", "foregone_yield_usd": "0", "residual_stress_loss_usd": "150000.00", "break_even_probability": null, "objective_usd": "22500.00", "quote_status": "proxy" },
      { "exit_fraction": "0.25", "fees_usd": "750.00", "gas_usd": "40.00", "price_impact_usd": "1870.32", "estimated_exit_cost_usd": "2660.32", "foregone_yield_usd": "244.52", "residual_stress_loss_usd": "112500.00", "break_even_probability": "0.0775", "objective_usd": "19779.84", "quote_status": "proxy" },
      { "exit_fraction": "0.50", "fees_usd": "1500.00", "gas_usd": "40.00", "price_impact_usd": "7462.69", "estimated_exit_cost_usd": "9002.69", "foregone_yield_usd": "489.04", "residual_stress_loss_usd": "75000.00", "break_even_probability": "0.1266", "objective_usd": "20741.73", "quote_status": "proxy" },
      { "exit_fraction": "0.75", "fees_usd": "2250.00", "gas_usd": "40.00", "price_impact_usd": "16749.38", "estimated_exit_cost_usd": "19039.38", "foregone_yield_usd": "733.56", "residual_stress_loss_usd": "37500.00", "break_even_probability": "0.1758", "objective_usd": "25397.94", "quote_status": "proxy" },
      { "exit_fraction": "1.00", "fees_usd": "3000.00", "gas_usd": "40.00", "price_impact_usd": "29702.97", "estimated_exit_cost_usd": "32742.97", "foregone_yield_usd": "978.08", "residual_stress_loss_usd": "0", "break_even_probability": "0.2248", "objective_usd": "33721.05", "quote_status": "proxy" }
    ],
    "recommendation": "REDUCE",
    "recommended_exit_fraction": "0.25",
    "reason": "With a 15% probability of this depeg, reducing by 25% has the lowest expected cost (19779.84 USD vs 22500.00 USD for staying). Reducing by 25% beats staying if the user's probability of this depeg exceeds 7.75%. Exit costs are proxy estimates.",
    "warnings": [
      "Exit costs use the constant-product proxy on assumed depth; replace with executable quotes.",
      "proxy_quotes: recommendation relies on proxy exit costs; confirm with executable quotes before trading."
    ]
  }
}
```

Without `probability` the same request returns exactly the section 11.8 fixture (`mode = conditional_stress`, `INSUFFICIENT_DATA`).

### Errors

Body: `{"status": "error", "error": {"code": "...", "message": "..."}}`.

| HTTP | `code` | When |
|------|--------|------|
| 400 | `unsupported_schema_version` | `schema_version` is not `"1.0"` |
| 404 | `unknown_portfolio` | `portfolio_id` does not match the portfolio |
| 404 | `unknown_position` | `position_id` is not in the portfolio |
| 422 | `invalid_request` | missing field, unknown `scenario_id` / `include`, incomplete `inputs`, `probability` not a decimal string |
| 422 | `invalid_inputs` | inputs are inconsistent (ids, horizon), probability outside [0, 1], missing conditional loss |

### Optional blocks

- `sensitivity`: `objective_vs_probability` (J(x) for p = 0 … 0.50 in 0.01 steps, per exit fraction, plus the best fraction at each p) and `break_even_vs_depth` (p* per exit fraction with the exit venue depth divided by 1, 2, 5, 10). First warning is always "Assumption-driven…".
- `portfolio_summary`: per-position choices added up (no joint optimisation, section 4.2), stay loss, chosen-action totals (`null` while any position is `INSUFFICIENT_DATA`), shared exit venue warning.

## Formulas (one line each)

For exit fraction x ∈ {0, 0.25, 0.50, 0.75, 1}, with S = gross value sold (x × collateral or x × token value, pre-shock), L = `conditional_loss_usd` from P2:

- **Price impact (proxy)** = S² / (D + S), D = pre-crisis `effective_depth_usd` of the exit venue.
- **ExitCost(x)** = S × `fee_rate` + `gas_usd` + price impact (0 when x = 0).
- **ResidualLoss(x)** = (1 − x) × L.
- **ForegoneYield(x)** = x × carry × horizon_days / 365; carry = collateral × supply APY − debt × borrow APY (borrow), or value × token APY (token / PT).
- **Break-even p*(x)** = (ExitCost(x) + ForegoneYield(x)) / (L − ResidualLoss(x)), floored at 0; `null` when nothing is avoided.
- **J(x)** = ExitCost(x) + p × ResidualLoss(x) + ForegoneYield(x); recommendation = argmin J (ties → smaller trade): x = 0 STAY, 0 < x < 1 REDUCE, x = 1 EXIT.

## Recommendation rules (section 8)

| Situation | `mode` | Recommendation |
|-----------|--------|----------------|
| no probability | `conditional_stress` | `INSUFFICIENT_DATA`, `objective_usd = null`, table + p* shown |
| probability, all quotes `executable` / `pool_reserves` | `expected_cost` | argmin J(x) |
| probability, any `proxy` quote | `expected_cost` | argmin J(x), plus a warning starting with `proxy_quotes` |
| no price at all | `conditional_stress` | `INSUFFICIENT_DATA`, only the 0 % row (`quote_status = unavailable`) |

`reason` always names the best break-even threshold (lowest p*), and says so when no exit can beat staying (no loss, or every p* > 100 %).

## Plugging a real price (P1)

A quote source is `source(venue_id, venue, size_usd) -> Decimal | None`: price impact in USD (positive, excluding venue fee and gas), or `None` when it has no price for that size.

```python
from backend.execution.exit_cost import ExitCostEstimator
estimator = ExitCostEstimator(executable=my_aggregator_quote, pool_reserves=my_pool_math)
decide_position(portfolio, snapshot, risk_result, scenario_request, "aave_01", estimator=estimator)
```

Sources are tried per exit size in priority order; `quote_status` reports the one that answered. A venue whose `quote_method` claims a better method than the one used is flagged in `warnings`.

## Assumptions

- Exits happen **before** the scenario, at pre-shock prices and pre-crisis depth (section 4.2). In the liquidity scenario only the avoided loss changes, never the exit cost.
- Decisions are per position; the portfolio summary adds them up without joint optimisation.
- Borrow positions unwind pro rata: sell x × collateral, repay x × debt (USDC, no price impact); LTV unchanged.
- Cash earns 0; borrowed proceeds are outside the portfolio.
- Probabilities are user inputs, never estimated by P3. Decimal maths throughout; rounding only at output (USD 2 dp, ratios 4 dp); numbers are strings in JSON.

## Limitations

- **The proxy overstates price impact on stable pools.** Constant-product maths ignores stableswap curves (Curve) and the Pendle AMM; real quotes should be lower for USDe/USDC and sUSDe/USDC.
- **Exiting sUSDe is not instantaneous.** Redeeming sUSDe for USDe goes through Ethena's cooldown period, so a fast exit depends on secondary-market liquidity (the venue), which is what the model prices.
- **Shared venues are priced standalone.** `ethena_susde_01` and `morpho_01` both sell on `venue:susde_usdc`; a simultaneous exit costs more than the sum of standalone costs (flagged in the portfolio summary).
- **Residual loss is pro rata (blueprint rule).** In the liquidity crisis the forced-sale haircut is convex, so (1 − x) × L overstates the remaining risk (aave_01 keeping 75 %: 81,325 USD real vs 107,143 USD pro rata), which biases towards exiting.
- **Unpriced rows are omitted.** Cost fields are not nullable in schema v1, so an exit size with no price is dropped rather than filled with an invented number.

## Open points for the team

- **P1:** `morpho_01` has `collateral_supply_apy = 0.00`, but its sUSDe collateral accrues ≈7 %/yr through the exchange rate (same as `ethena_susde_01`). With 0 % the carry is −110,000 USD/yr instead of ≈ +100,000 USD/yr, which lowers its break-even probabilities.
- **P3 schema (additive):** allow `null` cost fields when `quote_status = "unavailable"`, so the UI can show "no price" instead of a missing row.
- **P2 / team:** compute the liquidity-scenario residual loss on the remaining size instead of pro rata.
- **Team:** with zero conditional loss and no probability, rule 1 returns `INSUFFICIENT_DATA` although STAY dominates for every probability; returning STAY would not invent a probability.

## Running the tests

From the repository root:

```bash
python3 -m pip install pytest
python3 -m pytest backend/execution -v      # 59 tests
python3 -m backend.execution.decision        # prints the aave_01 decision and checks it against the 11.8 fixture
```


## Dashboard integration

`backend.execution.integration.decide(portfolio, snapshot, request, position_id, risk_result)`
connects P3 to risk. The API passes the exact saved result from `/simulate` when the frontend
requests a decision by `simulation_id`. Unknown simulations and cross-portfolio lookups are
rejected. Frontend run IDs are unique, so background stress comparisons cannot overwrite the
main run's saved result. Request-based calls remain supported.

The adapter uses the risk result's pre-shock marks, shares the risk engine's snapshot quote
curve and labels extrapolation as proxy. Lending supplies withdraw from idle market liquidity:
fractions exceeding that liquidity are omitted, and locked supply is not treated as a loss.
Withdrawal fee/gas inputs are currently absent and explicitly flagged as shown at zero.
Negative conditional losses (carry gains) stay signed in residual results.

Offline `risk_surface.json` decisions are generated through this same adapter. The Scenario
Lab displays a position's exit table next to its risk result; the Decision Engine page keeps
the detailed view. P3 produces decision analysis, not on-chain trade submission.

---

# Crisis mode (scenario assumed certain)

The prevention mode above answers "should I act in case it happens?" with break-even probabilities. The crisis mode answers the risk analyst's question: **"this scenario happens — what do I do with each position to lose the least?"** No probability is used. Both modes coexist; `decision_result` is unchanged.

## Modules

```
backend/execution/
├── crisis.py     CrisisModel: every action priced per position (early / late), portfolio strategies
├── hedging.py    hedge universe (USDC, USDT, PYUSD, RLUSD), scenario shock check, rotation strategies
├── advisor.py    AI advisor: explanation + 3 strategies built from available actions, re-priced by the engine
└── tests/        test_crisis.py · test_crisis_portfolio.py · test_advisor.py · test_crisis_api.py
```

## Model (one line each)

- **Loss if kept** = P2 conditional loss minus `execution_haircut` (a forced-sale cost is only paid when selling).
- **Exit cost** = fees + gas + price impact on the exit venue at the scenario's depth `k = 1 − exit_liquidity_reduction_pct` (P2 `exit_cost`, executable KyberSwap curves).
- **Total of an action** = exit cost + foregone yield + loss still suffered on what is kept; lowest total wins, ties keep.
- **Early reaction**: act at pre-shock prices; price loss, liquidation penalty and lender bad debt are avoidable.
- **Late reaction**: the price loss is already incurred (`already_incurred_usd`, never shown as avoidable); only the liquidation penalty remains avoidable.
- **Actions**: hold · sell 25/50/75/100 % (pro rata) · deleverage to safety (P2 `deleverage_needed`: HF 1.05 / 95 % of LLTV) · withdraw (lenders, within idle market liquidity).
- **Portfolio strategy** = one action per position; sales on a shared venue are priced jointly (`shared_venue_penalty_usd`).
- **Candidates**: `hold_all`, `exit_all`, `min_loss` (per-position best, then coordinated for shared venues), `protect_liquidations`, `rotate_into_<stable>` (on-demand quotes only); duplicates carry `same_as`.

## Hedge universe

USDC, USDT, PYUSD, RLUSD with issuer (P1 registry), snapshot price, `shocked_in_scenario` (a shocked asset is never a hedge) and routes: `snapshot_quotes` (USDC venues), `on_demand_quote` (P1's KyberSwap route, network, opt-in), `unavailable` (with reason). Short perps, options and depeg cover are listed as **not priced**: no price source exists in the project.

## AI advisor

The engine computes; the LLM explains and composes. Context = computed figures only (no addresses, no secrets). Output = schema-bound JSON: `scenario_explanation`, `position_assessments`, exactly 3 `strategies` (timing + actions from the available list), `recommended_strategy_index`, `hedging_notes`, `caveats`.

Safeguards: every AI strategy is re-priced by `CrisisModel.evaluate` (`computed_result` is the only source of figures); an unavailable action, an unknown position or a schema violation rejects the advice while keeping the plan; numbers absent from the context are listed in `ungrounded_numbers`.

Configuration (backend only, `.env` is git-ignored):

```dotenv
GEMINI_API_KEY=...
ADVISOR_MODEL=            # optional; defaults to RISK_ASSISTANT_MODEL (P2's Gemini setting)
```

The client is pluggable (`llm(system, context, schema) -> dict`); `GeminiClient` follows P2's `backend/api/risk_assistant.py` protocol.

## Endpoint: `POST /api/v1/crisis-advice`

| Field | Meaning |
|---|---|
| `request` | a scenario request (any of the seven scenarios), or |
| `simulation_id` | a saved `/simulate` run (exact same risk result) |
| `advice` | `true` (default) to ask the AI; `false` for the computed plan only |
| `on_demand_quotes` | `true` to price hedge routes live on KyberSwap (network) |

```json
{ "request": { "...": "contracts/fixtures/stress_portfolio_01/scenario_request_combined.json" }, "advice": false }
```

Response (combined crisis, trimmed):

```json
{
  "plan": {
    "scenario_id": "combined_crisis", "horizon_days": 7, "depth_factor": "0.2",
    "positions": [{
      "position_id": "ethena_susde_01", "holding_loss_usd": "150223.60",
      "early": { "best": { "action": "sell", "fraction": "1.00", "total_loss_usd": "11907.20", "saving_vs_hold_usd": "138316.40" } },
      "late":  { "already_incurred_usd": "150223.60", "best": { "action": "hold", "fraction": null, "total_loss_usd": "0.00" } }
    }],
    "strategies": { "early": [{
      "strategy_id": "min_loss",
      "choices": { "ethena_susde_01": { "action": "sell", "fraction": "0.75" }, "aave_01": { "action": "sell", "fraction": "1.00" },
                   "morpho_01": { "action": "sell", "fraction": "1.00" }, "pendle_01": { "action": "sell", "fraction": "0.50" },
                   "lend_susde_01": { "action": "withdraw", "fraction": "1.00" }, "lend_usde_01": { "action": "withdraw", "fraction": "1.00" } },
      "total_loss_usd": "200047.41", "saving_vs_hold_all_usd": "796653.34", "shared_venue_penalty_usd": "79939.20"
    }]},
    "hedging": { "shocked_assets": { "USDe": "USDe depeg in this scenario" }, "assets": [{ "asset": "USDC", "usable_as_hedge": true }] }
  },
  "advice": null,
  "advice_error": null
}
```

With `advice: true`, `advice` holds the AI output with a `computed_result` per strategy. If the AI fails (no key, rejected key, quota, invalid output), `advice` is `null`, `advice_error` explains why (`{status, message}`) and the plan is still returned — never a 500, never invented advice.

## Limitations

- Late exits in `combined_crisis` ignore liquidators selling ahead of us (cost understated).
- Late lender withdrawals are not modelled; lender withdrawal fees and gas are not in the snapshot (shown as zero).
- Offline, USDC is the only priced hedge; USDT has no snapshot price; PT-sUSDe and RLUSD are not in P1's token registry.
- Deleverage keeps the price loss proportional to the collateral kept (approximation).

## Tests

```bash
.venv/bin/python -m pytest backend/execution -q     # prevention + crisis mode
```
