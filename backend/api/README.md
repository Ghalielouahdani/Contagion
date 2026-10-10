# backend/api/ — FastAPI orchestration (owner: P4)

Serves the routes the frontend calls (`frontend/src/data/api.ts`). Every route takes an optional `?set=<fixture set>` (default: env `FIXTURE_SET` or `demo_ethena_01`).

```bash
.venv/bin/uvicorn backend.api.main:app --reload --port 8000
.venv/bin/python -m pytest backend/api
```

Assistant setup:

```bash
ollama pull llama3.2
ollama serve
OLLAMA_MODEL=llama3.2 .venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

The assistant uses the no-cost-ai catalog's local Ollama option. It refuses non-local model URLs so the portfolio and risk context stay on the machine. If Ollama is unavailable, `/api/v1/assistant` returns an explicit deterministic fallback instead of silently pretending it called a model.

| Method | Path | Backed by |
|---|---|---|
| GET | `/api/v1/health` | sets available, module modes |
| GET | `/api/v1/portfolio` | fixture set |
| POST | `/api/v1/discover` | fixture graph (P1 live discovery pending) |
| GET | `/api/v1/market-snapshot` | fixture snapshot |
| POST | `/api/v1/simulate` | **live risk engine** (scenario request validated against schema v1) |
| POST | `/api/v1/analyze` | **live** risk analytics (value for the fund) |
| POST | `/api/v1/grid` | **live** loss / liquidation heatmap over two parameters |
| POST | `/api/v1/decide` | **provisional** decision from the risk engine (blueprint section 8), exact on the golden fixture; P3 replaces it |
| POST | `/api/v1/assistant` | local Ollama model grounded in visible fixture/API data, explicit fallback if unavailable |

Composes P1 → P2 → P3 and owns no financial formulas: these live in `backend/risk` and, later, `backend/execution`.
