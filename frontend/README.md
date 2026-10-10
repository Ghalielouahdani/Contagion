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

## Definition of done

A reviewer loads the portfolio, inspects the dependencies, runs both scenarios and understands the STAY/REDUCE/EXIT reasoning in under three minutes, even offline.
