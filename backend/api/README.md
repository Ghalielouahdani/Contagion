# backend/api/ — FastAPI orchestration (owner: P4)

Serves the routes the frontend calls (`frontend/src/data/api.ts`). Every route takes an optional `?set=<fixture set>` (default: env `FIXTURE_SET` or `stress_portfolio_01`).

```bash
.venv/bin/uvicorn backend.api.main:app --reload --port 8000
.venv/bin/python -m pytest backend/api
```

| Method | Path | Backed by |
|---|---|---|
| GET | `/api/v1/health` | sets available, module modes |
| GET | `/api/v1/portfolio` | fixture set |
| POST | `/api/v1/discover` | P1 discovery: stored snapshot by default; `?discovery=replay` or `live` activates new inputs |
| GET | `/api/v1/market-snapshot` | fixture snapshot |
| POST | `/api/v1/simulate` | **live risk engine** (scenario request validated against schema v1) |
| POST | `/api/v1/analyze` | **live** risk analytics (value for the fund) |
| POST | `/api/v1/grid` | **live** loss / liquidation heatmap over two parameters |
| POST | `/api/v1/decide` | P3 execution decision consuming the matching risk result, snapshot and request |
| POST | `/api/v1/assistant` | 501: the assistant runs client-side |

Composes P1 → P2 → P3 and owns no financial formulas: these live in `backend/risk` and `backend/execution`.


Execution is linked by run: the frontend submits a unique request ID to `/simulate`, then
sends its returned `simulation_id` to `/decide` for each position. The server keeps that
run's request, risk result, portfolio and snapshot together, scoped to the portfolio.
P3 consumes those exact inputs; unknown run IDs return 404. Request-based decisions remain
available and compute risk against the selected active discovery inputs.

Stored, replayed and live discovery share the same contract shapes. Replay/live discovery
activates its graph and snapshot for simulation and analysis; stored discovery resets them.
This state and saved simulations are in memory and disappear on server restart.
