[BelemCapital_EPFL-Hackathon_DeFi-Risk-Dependency-Challenge_EN_v1.pdf](https://github.com/user-attachments/files/33281645/BelemCapital_EPFL-Hackathon_DeFi-Risk-Dependency-Challenge_EN_v1.pdf)
# DeFi Contagion

A stress-test engine for a crypto portfolio on real Ethereum markets. It discovers what each position really depends on (P1), computes what the portfolio loses if a shock happens and how the shock propagates (P2), and compares the cost of acting with the loss avoided (P3). It never predicts: every number is conditional on a scenario.

Spec: [DeFi_Contagion_Project_Blueprint_v2.md](DeFi_Contagion_Project_Blueprint_v2.md) · contracts: [contracts/](contracts/README.md) · verification log: [docs/verified_markets.md](docs/verified_markets.md)

## Run it end to end

```bash
# once
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"     # Python 3.12 or 3.13
(cd frontend && npm ci)

# API: P1 discovery -> P2 risk engine -> P3 decision engine
.venv/bin/uvicorn backend.api.main:app --reload --port 8000

# dashboard on the live API (another terminal); /api is proxied to :8000
cd frontend && npm run dev     # http://localhost:5173
```

| Setting | Values |
|---|---|
| `VITE_USE_FIXTURES` | `false` (default): risk and execution computed by the API · `true`: recorded engine results offline |
| `VITE_DISCOVERY` (API mode) | `stored` (default): the set's saved graph · `replay`: P1 discovery re-run from its recording (offline, ~1 s; sets with a recording) · `live`: P1 discovery on Ethereum now (`ETH_RPC_URL`, slower) |
| Portfolio (`VITE_FIXTURE_SET`) | `stress_portfolio_01` (default): six synthetic positions on recorded real Ethereum markets, shared by all seven scenarios; [composition and sources](docs/stress_portfolio.md). Archived sets are explicit developer overrides. |

[Detailed scenario guide: mechanisms, formulas and result interpretation](docs/risk_scenarios.md).

Scenarios, each with its own controls: A USDe depeg · B liquidity crisis · C both together · D carry squeeze · E governance or oracle change · F dependency-node failure · G liquidation cascade.

## The whole chain without the dashboard

```bash
S=http://localhost:8000/api/v1; SET=live_ethena_01; H='content-type: application/json'
curl -s -X POST "$S/discover?set=$SET&discovery=replay" -H "$H" -d '{"schema_version":"1.0"}' | head -c 300
curl -s -X POST "$S/simulate?set=$SET" -H "$H" --data @contracts/fixtures/$SET/scenario_request.json | head -c 300
curl -s -X POST "$S/analyze?set=$SET"  -H "$H" --data @contracts/fixtures/$SET/scenario_request.json | head -c 300
curl -s -X POST "$S/decide?set=$SET"   -H "$H" \
  -d "{\"request\": $(cat contracts/fixtures/$SET/scenario_request.json), \"position_id\": \"aave_01\"}" | head -c 300
curl -s "$S/health?set=$SET"
```

## Tests

```bash
.venv/bin/python -m pytest                     # everything offline: contracts, P1 replay, P2, P3, API, end to end
.venv/bin/python -m pytest tests               # cross-module and end-to-end only
(cd frontend && npm run build)                 # type-check and bundle the dashboard
DISCOVERY_LIVE=1 .venv/bin/python -m pytest backend/discovery/tests/test_live.py   # network: real Ethereum
```

## Refresh the real data

```bash
.venv/bin/python -m backend.discovery discover --portfolio backend/discovery/examples/live_ethena_01.json --mode live --out /tmp/p1 --revalue
.venv/bin/python -m backend.discovery.build_lending_set contracts/fixtures/verified_lending_2026_10_10   # lenders, borrowers, exit curves
.venv/bin/python -m backend.risk.regenerate contracts/fixtures/<set>   # recompute stored results + offline surface (never overwrites golden values)
```

| Folder | Owner | Role |
|---|---|---|
| `backend/adapters`, `backend/discovery` | P1 | dependency graph and market snapshot from Ethereum (evidence on every edge) |
| `backend/risk` | P2 | scenarios A-G, contagion paths, analytics for the fund |
| `backend/execution` | P3 | STAY / REDUCE / EXIT from exit costs, residual loss and break-even probability ([concept and worked example](backend/execution/CONCEPT.md)) |
| `backend/api`, `frontend` | P4 | API orchestration and dashboard |
