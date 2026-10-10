# tests/ — cross-module and end-to-end tests (shared)

Unit tests live with each module (at least 3 per owner). This folder holds the tests that check **the modules fit together**.

Read: blueprint sections 12 (acceptance tests), 17 (integration checkpoints).

## What to write

1. **Contract tests:**
   - every file in `contracts/` validates against the schema v1 models;
   - IDs match across files (`portfolio_id`, `graph_id`, `snapshot_id`, every `position_id`);
   - in each risk result, `loss_components` sum to `conditional_loss_usd`, and the position totals reconcile with the portfolio total (plus the shared-venue penalty).
2. **Golden tests:** P2 and P3 in live mode, run on the fixture inputs, reproduce `risk_result*.json` and `decision_result.json`.
3. **End-to-end tests through the API:** call `/discover` → `/simulate` (both scenarios) → `/decide`. IDs stay stable and every response is valid.
4. **Offline test:** the full flow passes with the network disabled (fixture mode or frozen snapshot).

## Integration checkpoints (run all tests at each one)

1. All four modules run in fixture mode.
2. P1's real snapshot flows into P2.
3. P2's output feeds P3.
4. P4 demonstrates the whole workflow.
5. The demo is frozen and the offline fallback works.
