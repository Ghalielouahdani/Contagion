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

Two modes, same screens. In both, the sliders drive real risk-engine results.

| Mode | How | Risk numbers |
|---|---|---|
| Fixture (default, offline) | `VITE_USE_FIXTURES=true` or unset | Engine results precomputed for every slider value (`risk_surface.json`, loaded on demand), at a 7-day horizon |
| API | `VITE_USE_FIXTURES=false`, backend running | Live engine on the exact slider values, plus live analytics and per-position decisions |

`VITE_FIXTURE_SET` chooses the data set: `demo_ethena_01` (golden demo, default) or `verified_2026_10_10` (real markets verified on-chain, see `docs/verified_markets.md`).

Run the API mode:

```bash
.venv/bin/uvicorn backend.api.main:app --reload --port 8000   # repo root
cd frontend && VITE_USE_FIXTURES=false npm run dev              # /api is proxied to :8000
```

The graph lays itself out by node type, and highlights the selected position's contagion paths computed by the risk engine. The inspector lists those paths, any graph gaps, and the contagion hubs.

## Definition of done

A reviewer loads the portfolio, inspects the dependencies, runs both scenarios and understands the STAY/REDUCE/EXIT reasoning in under three minutes, even offline.
