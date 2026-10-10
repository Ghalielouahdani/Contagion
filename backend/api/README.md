# backend/api/ — owner: P4 (Frontend, API Orchestration & Demo)

The FastAPI layer that connects the modules: **P1 → P2 → P3**. It contains **no financial formulas**. It validates requests, calls the modules in order and returns their JSON.

Read: blueprint sections 9, 10, 16 P4, 17.

## Endpoints

| Method | Path                 | Does                                                                 |
|--------|----------------------|----------------------------------------------------------------------|
| GET    | `/api/v1/health`     | status, schema version, which modules are in fixture or live mode    |
| GET    | `/api/v1/portfolio`  | returns `portfolio.json`                                             |
| POST   | `/api/v1/discover`   | P1 → graph + snapshot                                                |
| POST   | `/api/v1/simulate`   | P1 → P2 → `risk_result`                                              |
| POST   | `/api/v1/decide`     | P1 → P2 → P3 → `decision_result` for one position                    |

## What to do, step by step

1. **Day one: serve the fixtures.** Every endpoint returns the section 11 files, so the frontend can be built immediately.
2. **Add a fixture/live switch per module** (e.g. env vars `DISCOVERY_MODE`, `RISK_MODE`, `EXECUTION_MODE`). Each teammate flips their own module to live once it works, without breaking the others.
3. **Check `schema_version` and IDs** on every request. A wrong version or an unknown `portfolio_id` returns a clear error.
4. **Handle errors properly:** if a module fails or data is missing, return its warnings to the UI rather than a 500 or invented numbers.
5. **Allow CORS** for the React dev server.

## Definition of done

The whole flow works end to end in fixture mode, and keeps working when any single module is switched to live.
