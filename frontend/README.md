# frontend/ — owner: P4 (Frontend, API Orchestration & Demo)

The judge-facing app: React + TypeScript + React Flow. Goal: **in under 3 minutes**, a judge follows shock → dependency → position impact → exit decision.

Read: blueprint sections 5 (user journey), 11 (data shown), 16 P4.

## Four views to build

1. **Portfolio overview:** the 4 positions with gross value, debt and net equity **side by side** (never present $10m gross as capital; net is $6.2m). Show data freshness (`as_of`) and observed / derived / assumed badges.
2. **Dependency graph** (React Flow):
   - colors per node type: asset, protocol, market, oracle, position, venue;
   - click an edge → a drawer shows its evidence (method, contract address or URL, timestamp, confidence);
   - highlight the critical path of the selected scenario;
   - make the **shared exit venue** visible (sUSDe holding and Morpho sell into the same pool);
   - warn on `documented`, `inferred` and `assumed` links.
3. **Scenario controls:** two presets (A: depeg -5%, B: liquidity -80%), plus sliders for depeg size, oracle pass-through override, oracle lag, liquidity reduction and horizon.
4. **Results and decision:**
   - before/after value per position; **distance to liquidation** as a gauge;
   - loss breakdown (repricing / impairment / liquidation / execution);
   - exit table for 0/25/50/75/100%: cost vs residual loss vs foregone yield, with the break-even probability on each row;
   - the recommendation and its reason. Show `INSUFFICIENT_DATA` honestly, with the "worth it if probability > p*" message.

## What to do, step by step

1. Build everything on the fixtures first (read them from `contracts/` or through the API in fixture mode).
2. Loading, error and empty states for every view; one-click reset.
3. Connect to the live API endpoints once each module is ready.
4. **Demo safety:** the app must run fully offline on fixtures. Prepare a demo script, screenshots and a backup recording.

## Data source

Portfolio Dashboard and Dependency Graph read the original portfolio baseline independently
of stress runs. Editing sliders changes the draft only. Run updates Scenario Lab, its
contagion overlay, Risk Engine and Decision Engine; baseline holdings, dependency labels
and evidence stay unchanged. Portfolio cards open their original dependencies.

Two modes, same screens. Choose a scenario, adjust its parameters, then click **Run scenario** to submit it against the selected portfolio. The unified stress portfolio is the default for all seven scenarios. See [portfolio composition](../docs/stress_portfolio.md). Editing controls keeps the last run visible with a pending-changes notice; graph paths, decisions and assistant context describe that last submitted run.

| Mode | How | Risk numbers |
|---|---|---|
| Recorded results (offline) | `VITE_USE_FIXTURES=true` | Engine results precomputed for every slider value (`risk_surface.json`, loaded on demand), at each scenario preset's horizon |
| API (default) | `VITE_USE_FIXTURES=false` or unset, backend running | Live engine on the exact slider values, plus live analytics and per-position decisions |

`stress_portfolio_01` is the single default portfolio: synthetic allocations on recorded real markets. `VITE_FIXTURE_SET` can explicitly select an archived development set for regression checks.

Run the API mode:

```bash
.venv/bin/uvicorn backend.api.main:app --reload --port 8000   # repo root
cd frontend && VITE_USE_FIXTURES=false npm run dev              # /api is proxied to :8000
```

API mode defaults to `VITE_DISCOVERY=stored`: computations run now, but market inputs
come from the selected set's saved files. To refresh market inputs through Ethereum
RPC and protocol APIs before each run, start the frontend with:

```bash
VITE_USE_FIXTURES=false VITE_DISCOVERY=live VITE_FIXTURE_SET=live_ethena_01 npm run dev
```

The frontend waits for discovery before requesting the snapshot, simulation and
analytics, then requests execution decisions using the returned simulation ID.
`ETH_RPC_URL` can be set on the backend process to override its public RPC.
Discovery failures are displayed as errors; API requests do not fall back to demo
results. The unified portfolio includes lender supplies, which the generic live
discovery adapter does not yet support; use stored observations for that portfolio. `VITE_DISCOVERY=replay` runs discovery against a recorded cassette instead.

Live discovery still uses the selected portfolio file for position quantities.
It does not import a wallet's balances. Inspect snapshot and decision warnings:
missing executable quotes may use declared liquidity proxies, and missing lender
withdrawal fees or gas may be represented as zero with a warning. Stress shocks
and scenario probabilities remain user assumptions. Execution produces decisions,
not signed transactions or fork-based transaction simulations.

Run keeps the Scenario Lab open with results, loss components and the Contagion Graph below: scenario factors and portfolio paths are highlighted, position nodes show their computed losses, and the overview lists equity and liquidation status. Switch between all portfolio paths and the selected position. The inspector reads propagation from the factor to the position; graph edges retain their dependency direction. Shared-venue costs and the combined crisis liquidation-selling increment are displayed separately. Filter propagation channels to isolate USDe price, backing, exchange rate, yields or exit liquidity. The stress comparison runs five or six deterministic shock levels on the same portfolio and plots portfolio and position losses. API mode holds submitted assumptions fixed; offline mode uses the preset surface. No probability distribution is implied. Multiple paths never duplicate a position loss. This is an explanation of the engine result, not an iterative liquidation cascade.

The graph lays itself out by node type, and highlights the selected position's contagion paths computed by the risk engine. The inspector lists those paths, any graph gaps, and the contagion hubs.

## Definition of done

A reviewer loads the portfolio, inspects the dependencies, runs both scenarios and understands the STAY/REDUCE/EXIT reasoning in under three minutes, even offline.
