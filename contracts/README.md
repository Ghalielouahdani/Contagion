# contracts/ — schema v1 integration contract (shared by everyone)

This folder is how the four modules talk to each other. Each module reads JSON files from here and writes JSON in exactly the same shape. As long as everyone respects these shapes, P1–P4 can work in parallel without waiting for each other.

Read: blueprint sections 4.2 (conventions), 9.1 (parallelism contract), 11 (all fixtures), 17 (ownership).

## Files to create at kickoff

Copy each JSON block from blueprint section 11 into its own file:

| File                              | Owner | Produced from                          | Consumed by |
|-----------------------------------|-------|----------------------------------------|-------------|
| `portfolio.json`                  | P1    | fictional portfolio (input)            | everyone    |
| `dependency_graph.json`           | P1    | discovery adapters                     | P2, P4      |
| `market_snapshot.json`            | P1    | discovery adapters                     | P2, P3      |
| `scenario_request.json`           | P4    | UI controls (scenario A preset)        | P2, P3      |
| `scenario_request_liquidity.json` | P4    | UI controls (scenario B preset)        | P2, P3      |
| `risk_result.json`                | P2    | risk engine, scenario A                | P3, P4      |
| `risk_result_liquidity.json`      | P2    | risk engine, scenario B                | P3, P4      |
| `decision_result.json`            | P3    | decision engine                        | P4          |

## What the team must do here

1. **Freeze schema v1 together during the first 60–90 minutes.** Agree on the field names, IDs, units and sign conventions. After the freeze, nobody changes a file's shape alone.
2. **Write a schema/model for each file** (Pydantic v2 models, shared by the backend). Every module validates what it reads and what it writes.
3. **Treat the numbers as golden test values.** The fixtures are mutually consistent: P2 must reproduce `risk_result*.json` from the portfolio and the snapshot, and P3 must reproduce `decision_result.json`.
4. **Make changes through the owner.** Need a new field? Ask the owner of that file, bump the version if the change breaks other modules, and update the fixture and the model in the same PR.

## Rules that apply to every file

- `schema_version` is `"1.0"`; `portfolio_id`, `graph_id`, `snapshot_id` and `request_id` stay stable across files.
- Numbers are **strings** (Decimal), never floats. Values are in USD, rates are decimal fractions (`"0.05"` = 5%), timestamps are ISO-8601 UTC.
- Losses and costs are **positive**; shocks are **signed** (`"-0.05"` = price down 5%).
- Every object that holds numbers has a `source_type`: `observed` / `derived` / `assumed` / `fictional` / `user_scenario`.
- Placeholders (`TO_VERIFY_...`) stay visible until P1 replaces them with verified values. Never silently fill them.
