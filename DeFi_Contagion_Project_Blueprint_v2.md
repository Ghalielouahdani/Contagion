Version 1.1 • 10 October 2026 • Team of four • MVP scope: Ethereum / Ethena / Aave / Morpho / Pendle

## Changes in v1.1

- sUSDe is now valued from an explicit exchange rate (sUSDe → USDe) and a market price, both in the snapshot.
- Pendle PT is priced below 1 before maturity: the snapshot carries PT price, maturity and implied APY.
- Exit liquidity is defined for every position, through shared **exit venues**; exiting a collateralized borrow is defined (pro-rata unwind).
- Snapshot carries yields (staking, supply, borrow, PT implied), so foregone yield in J(x) is computable.
- Scenario A parameters complete: oracle pass-through per market (with optional override), oracle lag, backing impairment, PT implied-yield shock.
- risk_result carries net equity before/after, loss components, a risk-metric block with distance-to-liquidation, and source_type. A liquidity-crisis risk_result fixture is added.
- decision_result carries cost components, foregone yield and break-even probability per exit option.
- Morpho position now uses sUSDe collateral, so Aave and Morpho transmit the same shock through different channels.
- Fixture numbers are recomputed to be mutually consistent (section 11). Formatting of sections 11 and 16 fixed.

# 1. Executive summary

DeFi Contagion is a decision-support prototype for a crypto portfolio manager. Given a fictional portfolio built from real Ethereum markets, it discovers verifiable dependencies, simulates how a USDe-related shock affects positions across Ethena, Aave, Morpho and Pendle, and compares the economics of holding versus reducing or exiting exposure.

The prototype is NOT a live trading system, an automated incident predictor or an audit of all DeFi. The first version uses fictional holdings, real protocol configurations where accessible, two user-controlled scenarios and transparent assumptions. No wallet connection or real transactions are required.

# 2. Crypto and DeFi explained from zero

## 2.1 Blockchain, tokens and smart contracts

A blockchain is a shared ledger recording transactions. Ethereum is the blockchain selected for the MVP. A token is a transferable digital asset recorded by a smart contract; a smart contract is code executed by the blockchain. Wallets hold the credentials used to authorize actions; our MVP does not need to access them.

## 2.2 What is DeFi?

Decentralized finance (DeFi) is a set of financial services implemented through smart contracts: lending, borrowing, trading, staking and yield strategies. Users can hold several interconnected positions, even when a portfolio dashboard displays only a few assets.

## 2.3 Our four ecosystems

| Name   | Simple explanation                                                    | Why it matters                                              |
|--------|-----------------------------------------------------------------------|-------------------------------------------------------------|
| Ethena | Issues USDe, a synthetic dollar, and offers sUSDe staking exposure.   | Core source of common economic dependencies.                |
| Aave   | Lending and borrowing markets using collateral and liquidation rules. | A price shock can move health factors toward liquidation.   |
| Morpho | Lending markets with market-specific collateral, oracle and LLTV.     | The same shock can affect borrowers differently.            |
| Pendle | Markets for tokenized future yield, including principal tokens (PT).  | Maturity, redemption claims and AMM liquidity alter impact. |

## 2.4 Essential concepts

| Term                     | Plain-language meaning                                                                                                   |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------|
| USDe depeg               | USDe trades away from its intended ~1 USD market price; this does not automatically prove permanent backing loss.        |
| sUSDe                    | A staking-related claim on USDe; its exchange rate and market price must be modeled separately.                          |
| sUSDe exchange rate      | USDe redeemable per sUSDe share (grows with staking yield). Redemption is subject to a cooldown, so it is not instant exit. |
| Collateral               | Asset pledged to secure a loan.                                                                                          |
| Liquidation              | Protocol mechanism that may repay debt by seizing collateral when risk thresholds are crossed.                           |
| Oracle                   | A price source used by smart contracts; it may differ from the spot market price.                                        |
| Oracle pass-through      | Fraction of a market price move that the protocol's oracle reflects (1 = fully, 0 = not at all, e.g. exchange-rate oracle). |
| Distance to liquidation  | How far the collateral's oracle price can fall, in %, before the position becomes liquidatable.                         |
| AMM / liquidity pool     | On-chain venue where tokens can be swapped; large orders may move the price.                                             |
| Exit venue               | The pool or route used to sell a position. Several positions may share one venue, and then compete for its liquidity.   |
| PT / YT                  | Pendle principal and yield tokens: different economic rights tied to an underlying yield-bearing asset.                  |
| PT implied APY           | Fixed yield implied by the PT's discount to its redemption value at maturity.                                            |
| TVL                      | Total value locked in a protocol; not the same as unique economic exposure.                                              |
| Slippage                 | Difference between reference price and actual execution price.                                                           |

# 3. The real portfolio manager problem

A position can depend on its settlement chain, underlying asset, protocol, oracle, collateral mechanics and exit market. A shock in one component may affect multiple holdings through different channels. The user needs a traceable answer to: what is exposed, how can the incident propagate, how much might be lost, and does the cost of exiting justify taking action?

Example: a 5% USDe market depeg could directly affect USDe holdings; a USDe-collateralized borrower may approach liquidation if its oracle reflects the drop; a Pendle PT may reprice through changed redemption expectations and liquidity. None of these impacts should be assumed identical.

# 4. Exact MVP scope and boundaries

- Ethereum mainnet data only; selected markets from Ethena, Aave, Morpho and Pendle.
- Input is a fictional portfolio of four positions, with explicit balances, debt, collateral and market identifiers; actual protocol markets and parameters are verified before demo.
- Two scenarios: (A) USDe market-price depeg and (B) liquidity crisis. Scenario horizon and shock severity are configurable.
- Automatic discovery via protocol-specific adapters; evidence and timestamps are attached to edges.
- Outputs: dependency graph, conditional position impacts, liquidation warnings, exit-cost curves, stay/reduce/exit comparison.
- Out of scope for MVP: wallet connection, automatic trading, predicting hacks, full Ethereum coverage, autonomous LLM judgments, live custody/backing data that are not publicly observable.

## 4.1 Fictional portfolio: initial target

| ID              | Illustrative position                                  | Gross value | Debt    | Net equity | Critical caveat                                                         |
|-----------------|--------------------------------------------------------|-------------|---------|------------|-------------------------------------------------------------------------|
| ethena_susde_01 | 1.6m sUSDe shares (× 1.25 USDe/share)                  | \$2.0m      | –       | \$2.0m     | Record shares and exchange rate, not just a USD number.                 |
| aave_01         | 3.0m USDe collateral, 1.8m USDC debt                   | \$3.0m      | \$1.8m  | \$1.2m     | Specify collateral, debt, oracle and eMode; market must exist.          |
| morpho_01       | 2.4m sUSDe collateral, 2.0m USDC debt                  | \$3.0m      | \$2.0m  | \$1.0m     | Specify exact market ID, oracle type and LLTV.                          |
| pendle_01       | 2.08m PT-sUSDe at ~0.9616 (maturity ~166 days)         | \$2.0m      | –       | \$2.0m     | Specify market address, PT token and maturity; choose a live market.    |
| **Total**       |                                                        | **\$10.0m** | **\$3.8m** | **\$6.2m** | Dashboard shows gross and net side by side; never sum gross as capital. |

These four lines are portfolio-design placeholders, NOT assertions that these exact markets exist today. The Aave and Morpho positions deliberately use different collateral (USDe vs sUSDe) so that one shock reaches them through different oracle channels. If P1 cannot find a live market matching a line, P1 picks the closest live market and the team updates the fixture once, at kickoff.

## 4.2 Modelling conventions (apply to every module)

- **Shocks are instantaneous** at `as_of`. `horizon_days` sets the window for foregone yield, borrow cost and the liquidity window; it does not add price drift.
- **Cash earns 0** in v1. USDC freed by an exit is held as cash.
- **Borrowed proceeds are outside the portfolio.** The USDC borrowed on Aave/Morpho is assumed to be already deployed elsewhere and not modeled; only the collateral, the debt and the carry of the position are in scope.
- **Exits happen at pre-shock prices** in the decision engine: the question is whether to act before the scenario occurs.
- **Decisions are per position** in v1. A portfolio-level summary adds up per-position choices but does not optimize them jointly.
- **Rounding:** USD values to 2 decimals, ratios to 4 decimals, only at output. Intermediate maths uses full precision (Decimal).

# 5. End-to-end user journey

- Open dashboard; inspect fictional portfolio, market timestamps and data-quality flags.
- Select a position; see its automatically generated dependency graph and click each edge to inspect evidence.
- Choose scenario A or B, shock magnitude and horizon; run deterministic simulation.
- Inspect before/after values, health factors / LTV, distance to liquidation, potential liquidation triggers and confidence limitations.
- Compare execution costs for 0%, 25%, 50%, 75% and 100% exit.
- Receive conditional STAY / REDUCE / EXIT recommendation, sensitivity to assumptions, and explanation of the causal path.

# 6. Dependency discovery: what automatic means

Adapters read protocol-specific on-chain contracts, APIs and documented configuration. They resolve the underlying assets, market parameters, oracles, contracts, chain and relevant liquidity routes. A common graph model normalizes the results. Protocol adapters are coded; individual market graphs and balances must not be hand-written as the final answer.

Each node has a stable ID and a type. Each directed edge states the relationship and the risk transmission channel, with evidence URL or contract address, as-of timestamp, discovery method and confidence. Off-chain Ethena backing/custody dependencies may be documented rather than directly observed and must be marked accordingly.

**Exit venues are graph nodes** (`venue:<id>`). Each position has an `exits_via` edge to the venue used to sell it. When two positions point to the same venue (in the fixture: `ethena_susde_01` and `morpho_01` both sell sUSDe), the graph makes the shared liquidity dependency visible and the liquidity scenario prices a joint exit.

## Example propagation chains

USDe market depeg → oracle repricing (if applicable) → collateral valuation → Aave health factor / Morpho LTV → liquidation eligibility. Separately: USDe shock → sUSDe market price → Pendle PT valuation → AMM exit quote. An oracle freeze or backing impairment would require a distinct mechanism, not a reused percentage multiplier.

# 7. Quantitative model and two scenarios

## 7.1 Scenario A: USDe market depeg

**Parameters** (in `scenario_request.json`):

| Parameter                     | Meaning                                                                                          | Default |
|-------------------------------|--------------------------------------------------------------------------------------------------|---------|
| `usde_spot_shock_pct`         | Move of the USDe market price (negative = depeg).                                                | -0.05   |
| `susde_market_beta`           | sUSDe market price move = beta × USDe move.                                                      | 1.0     |
| `backing_impairment_pct`      | Permanent loss of USDe backing; lowers the sUSDe exchange rate and every redemption claim.       | 0.00    |
| `oracle_pass_through_override`| If set, replaces every market's `oracle_pass_through` from the snapshot. `null` = use snapshot.  | null    |
| `oracle_lag_hours`            | Delay before the oracle reflects the move. v1 reports it and the liquidation window only; final metrics use the fully passed-through oracle. | 0 |
| `pt_implied_apy_shock`        | Additive change of the PT implied APY (stress widens the discount).                              | +0.03   |

**Valuation rules:**

- USDe position: loss = Q × (P_before − P_after).
- sUSDe market value (USD) = shares × exchange_rate × USDe_price × (1 + susde_market_beta × shock). Backing impairment multiplies exchange_rate by (1 + backing_impairment_pct).
- Oracle price used by a lending market = P_before × (1 + oracle_pass_through × market move). With pass-through 0 the oracle does not move and the health metric is unchanged even though the mark-to-market value fell.
- Pendle PT (v1 proxy, label `approximation`): PT_price_usd = USDe_price × 1 / (1 + implied_apy)^(days_to_maturity / 365). After the shock, use the shocked USDe price and implied_apy + `pt_implied_apy_shock`. At or after maturity, PT_price = redemption value.

**Risk metrics:**

- Aave: HF = Σ(collateral oracle value × liquidation threshold) / Σ(debt oracle value). Liquidatable if HF < 1. Distance to liquidation (single collateral, stable debt) = 1 − 1/HF.
- Morpho: LTV = debt value / collateral oracle value. Liquidatable if LTV > LLTV. Distance to liquidation = 1 − LTV/LLTV.
- Liquidatable does not mean immediately or fully liquidated.

## 7.2 Scenario B: liquidity crisis

**Parameters:** `exit_liquidity_reduction_pct` (fraction of venue depth lost, e.g. 0.80), `fundamental_value_shock_pct` (default 0), horizon.

Underlying economic claims may remain unchanged while realizable exit proceeds fall. The output separates **mark value** (unchanged) from **executable value** (what a full exit would actually realize).

**What exiting means per position type:**

| Type                    | Exit of fraction x                                                                                   |
|-------------------------|------------------------------------------------------------------------------------------------------|
| token_holding / pt_holding | Sell x × quantity on the position's exit venue.                                                   |
| collateralized_borrow   | Pro-rata unwind: withdraw x × collateral, sell it for USDC on the exit venue, repay x × debt, keep the remainder as cash. LTV is unchanged by a pro-rata unwind. |

**Execution cost (priority order):** (1) executable quote from an aggregator or the venue; (2) pool reserve / curve mechanics; (3) labeled proxy. The v1 proxy is a constant-product approximation on an **effective depth** D (USD), which is set per venue and labeled `assumed`:

haircut(size) = size² / (D + size)   (i.e. average price discount = size / (D + size))

Under the crisis, D_crisis = D × (1 − exit_liquidity_reduction_pct). This is a proxy, not a universal law; real venues (stableswap, Pendle AMM) must replace it when quotes are available.

**Shared venues:** position-level results assume the position exits alone. The portfolio-level result prices a **joint exit**: sizes of all positions on the same venue are summed, haircut computed once, and allocated pro rata. The joint figure is the one used for portfolio totals, and the gap versus the sum of standalone haircuts is reported as `shared_liquidity_penalty_usd`.

## 7.3 Avoid double counting

Separate underlying asset impairment, market repricing, liquidation penalty, borrowing liabilities and execution costs. A mark-to-market decline and a subsequent sale at the lower market price are not two independent losses. Aggregate portfolio impact using each position's net equity and shared risk factors, not summed protocol TVLs.

Each position impact reports `loss_components` that sum exactly to `conditional_loss_usd`:

| Component             | Owner | Scenario A                        | Scenario B                       |
|-----------------------|-------|-----------------------------------|----------------------------------|
| market_repricing      | P2    | mark-to-market move               | 0 unless fundamental shock       |
| backing_impairment    | P2    | from `backing_impairment_pct`     | 0                                |
| liquidation_penalty   | P2    | only if liquidatable (bonus × seized collateral) | 0                  |
| execution_haircut     | P2 (stress) / P3 (decision) | 0 (no forced sale)    | haircut of a full exit           |

## 7.4 Uncertainty and defensibility

The model computes conditional stress losses; it does not manufacture incident probabilities. A user may provide a scenario probability or range. Report sensitivity and break-even probabilities, with a prominent "assumption-driven" label. Missing oracle, market or liquidity data must produce warnings rather than invented precision.

Every object that carries numbers has a `source_type` (observed / derived / assumed / fictional / user_scenario). When an object mixes origins, a `field_sources` map overrides `source_type` per field.

# 8. Decision and execution engine

For exit fraction x in {0, .25, .50, .75, 1}, compare exit cost, remaining conditional loss and foregone yield over the same horizon.

- **ExitCost(x)** = trading fees + gas + price impact (haircut on the sold collateral or tokens, section 7.2, using **pre-crisis** depth: the exit happens before the scenario).
- **ResidualLoss_s(x)** = (1 − x) × conditional loss of the position under scenario s (pro-rata unwind keeps loss proportional).
- **ForegoneYield(x)** = x × position carry over the horizon. Carry = collateral or token yield − borrow cost, from `market_snapshot.yields`. Cash earns 0 (section 4.2).

Risk-neutral objective: J(x) = ExitCost(x) + Σ p_s × ResidualLoss_s(x) + ForegoneYield(x). Lower is better.

**Break-even probability** of option x versus staying (x = 0), for one scenario:

p*(x) = (ExitCost(x) + ForegoneYield(x)) / (ResidualLoss(0) − ResidualLoss(x))

If the user believes the scenario probability exceeds p*(x), option x beats staying. Report p* for every option.

**Recommendation rules:**

- No probability supplied → `mode = conditional_stress`; `objective_usd = null`; show the table and p*; recommendation `INSUFFICIENT_DATA` unless the user supplies p.
- Probability supplied and all quotes are `executable` or `pool_reserves` → `mode = expected_cost`; pick argmin J(x): x = 0 → STAY, 0 < x < 1 → REDUCE, x = 1 → EXIT.
- Any option with quote_status `proxy` → the recommendation can be shown but is flagged `proxy_quotes`. If no quote at all is available, output `INSUFFICIENT_DATA` instead of a fabricated optimal trade.

# 9. System architecture and responsibilities

Fictional portfolio JSON → Discovery adapters → Evidence-backed graph + normalized market snapshots → Risk simulator → Execution/decision optimizer → FastAPI → React dashboard. Each workstream develops independently against fixed JSON fixtures and schema versions.

| Owner | Module                      | Independent deliverable                                                                        | Can start with                             |
|-------|-----------------------------|------------------------------------------------------------------------------------------------|--------------------------------------------|
| P1    | Data & Dependency Discovery | Protocol adapters; validated markets; evidence-backed graph; market snapshots.                 | Static sample portfolio and graph fixture. |
| P2    | Quantitative Risk           | Two scenario engines; Aave HF, Morpho LLTV and Pendle valuation approximations; impact output. | Fixture market snapshots and graph.        |
| P3    | Execution & Decision        | Exit cost curves; 5 exit fractions; objective and break-even sensitivity; decision output.     | Fixture risk results and synthetic quotes. |
| P4    | Frontend & Integration      | React views; API endpoints; graph visualization; error states; full demo and pitch flow.       | All shared fixture JSON files.             |

## 9.1 Parallelism contract

- First 60–90 minutes: jointly freeze schema v1, position IDs, currencies, units, sign conventions, scenario IDs and endpoints.
- Each person owns one module and its tests; all modules accept fixtures before live connectors exist.
- P4 owns integration endpoints, not the financial formulas; P1 owns data truth, P2 impact math, P3 execution math.
- Merge early: first end-to-end fixture demonstration before polishing visuals.
- Every calculated value carries source_type (observed / derived / assumed), timestamp and warning flags.
- **Sign convention:** losses and costs are positive numbers; shocks are signed (`-0.05` = price down 5%).

# 10. API surface and repository

Endpoints: GET /api/v1/portfolio; POST /api/v1/discover; POST /api/v1/simulate; POST /api/v1/decide; GET /api/v1/health. Each request includes schema_version and a stable portfolio_id. A complete simulation may return references to graph_id and market_snapshot_id. Each module runs in `fixture` or `live` mode, switchable per module, so the API works end to end from day one.

Repository: contracts/ (versioned JSON fixtures and schemas), backend/adapters/, backend/discovery/, backend/risk/, backend/execution/, backend/api/, frontend/, tests/, docs/. Use Python 3.12/FastAPI, Pydantic v2, Web3.py, NetworkX, NumPy/SciPy, React/TypeScript and React Flow. LLM analysis is optional after the deterministic MVP works.

**Prerequisites before kickoff:** an Ethereum mainnet RPC endpoint (Alchemy/Infura key or public RPC), Node 20+, Python 3.12 (Python 3.14 may lack wheels for some libraries).

# 11. JSON interfaces — schema v1 examples

The following fixtures are the team's integration contract. Numerical values and addresses are illustrative placeholders, but they are **mutually consistent**: the risk and decision fixtures are what the section 7–8 formulas produce from the portfolio and snapshot fixtures. P2 and P3 use them as golden test cases. JSON uses USD as quote currency, decimal fractions for rates, ISO-8601 UTC timestamps, explicit units, and numbers as strings. IDs must remain stable across all files. Do not interpret example data as live protocol observations.

## 11.1 contracts/portfolio.json

```json
{
  "schema_version": "1.0",
  "portfolio_id": "demo_ethena_01",
  "as_of": "2026-10-10T08:00:00Z",
  "quote_currency": "USD",
  "positions": [
    {
      "position_id": "ethena_susde_01",
      "protocol": "ethena",
      "chain_id": 1,
      "position_type": "token_holding",
      "market_id": null,
      "asset_symbol": "sUSDe",
      "quantity": "1600000",
      "quantity_unit": "sUSDe_shares",
      "gross_value_usd": "2000000.00",
      "debt_value_usd": "0",
      "net_equity_usd": "2000000.00",
      "exit_venue_id": "venue:susde_usdc",
      "data_origin": "fictional"
    },
    {
      "position_id": "aave_01",
      "protocol": "aave",
      "chain_id": 1,
      "position_type": "collateralized_borrow",
      "market_id": "TO_VERIFY_AAVE_MARKET",
      "collateral_asset": "USDe",
      "collateral_quantity": "3000000",
      "debt_asset": "USDC",
      "debt_quantity": "1800000",
      "gross_value_usd": "3000000.00",
      "debt_value_usd": "1800000.00",
      "net_equity_usd": "1200000.00",
      "exit_venue_id": "venue:usde_usdc",
      "data_origin": "fictional"
    },
    {
      "position_id": "morpho_01",
      "protocol": "morpho",
      "chain_id": 1,
      "position_type": "collateralized_borrow",
      "market_id": "TO_VERIFY_MORPHO_MARKET_ID",
      "collateral_asset": "sUSDe",
      "collateral_quantity": "2400000",
      "debt_asset": "USDC",
      "debt_quantity": "2000000",
      "gross_value_usd": "3000000.00",
      "debt_value_usd": "2000000.00",
      "net_equity_usd": "1000000.00",
      "exit_venue_id": "venue:susde_usdc",
      "data_origin": "fictional"
    },
    {
      "position_id": "pendle_01",
      "protocol": "pendle",
      "chain_id": 1,
      "position_type": "pt_holding",
      "market_id": "TO_VERIFY_PENDLE_MARKET",
      "asset_symbol": "PT-sUSDe",
      "quantity": "2080000",
      "quantity_unit": "PT_tokens",
      "gross_value_usd": "2000055.14",
      "debt_value_usd": "0",
      "net_equity_usd": "2000055.14",
      "exit_venue_id": "venue:pendle_pt_susde",
      "data_origin": "fictional"
    }
  ],
  "totals": {
    "gross_value_usd": "10000055.14",
    "debt_value_usd": "3800000.00",
    "net_equity_usd": "6200055.14"
  }
}
```

## 11.2 contracts/dependency_graph.json

Partial example: it shows each node and edge type once. Live discovery must produce the full graph for all four positions.

```json
{
  "schema_version": "1.0",
  "graph_id": "graph_demo_01",
  "portfolio_id": "demo_ethena_01",
  "as_of": "2026-10-10T08:00:00Z",
  "nodes": [
    { "id": "asset:USDe", "type": "asset", "label": "USDe" },
    { "id": "asset:sUSDe", "type": "asset", "label": "sUSDe" },
    { "id": "protocol:ethena", "type": "protocol", "label": "Ethena" },
    { "id": "protocol:aave", "type": "protocol", "label": "Aave" },
    { "id": "market:aave_01", "type": "market", "label": "Selected Aave market" },
    { "id": "oracle:aave_01_usde", "type": "oracle", "label": "Aave USDe price oracle" },
    { "id": "position:aave_01", "type": "position", "label": "Aave fictional position" },
    { "id": "position:ethena_susde_01", "type": "position", "label": "sUSDe holding" },
    { "id": "position:morpho_01", "type": "position", "label": "Morpho fictional position" },
    { "id": "venue:susde_usdc", "type": "venue", "label": "sUSDe/USDC exit route" }
  ],
  "edges": [
    {
      "id": "edge:1",
      "source": "asset:USDe",
      "target": "protocol:ethena",
      "relation": "issued_by",
      "risk_channel": "issuer_backing",
      "evidence": { "method": "protocol_documentation", "reference": "https://docs.ethena.fi/", "observed_at": "2026-10-10T08:00:00Z", "status": "to_verify" },
      "confidence": "documented"
    },
    {
      "id": "edge:2",
      "source": "position:aave_01",
      "target": "market:aave_01",
      "relation": "position_in",
      "risk_channel": "collateral_liquidation",
      "evidence": { "method": "fixture", "reference": "fictional portfolio", "observed_at": "2026-10-10T08:00:00Z", "status": "assumed" },
      "confidence": "assumed"
    },
    {
      "id": "edge:3",
      "source": "market:aave_01",
      "target": "oracle:aave_01_usde",
      "relation": "prices_collateral_with",
      "risk_channel": "oracle_repricing",
      "evidence": { "method": "onchain_call", "reference": "TO_VERIFY_ORACLE_ADDRESS", "observed_at": "2026-10-10T08:00:00Z", "status": "to_verify" },
      "confidence": "assumed"
    },
    {
      "id": "edge:4",
      "source": "asset:sUSDe",
      "target": "asset:USDe",
      "relation": "redeemable_for",
      "risk_channel": "exchange_rate",
      "evidence": { "method": "protocol_documentation", "reference": "https://docs.ethena.fi/", "observed_at": "2026-10-10T08:00:00Z", "status": "to_verify" },
      "confidence": "documented"
    },
    {
      "id": "edge:5",
      "source": "position:ethena_susde_01",
      "target": "venue:susde_usdc",
      "relation": "exits_via",
      "risk_channel": "exit_liquidity",
      "evidence": { "method": "fixture", "reference": "fictional portfolio", "observed_at": "2026-10-10T08:00:00Z", "status": "assumed" },
      "confidence": "assumed"
    },
    {
      "id": "edge:6",
      "source": "position:morpho_01",
      "target": "venue:susde_usdc",
      "relation": "exits_via",
      "risk_channel": "exit_liquidity",
      "evidence": { "method": "fixture", "reference": "fictional portfolio", "observed_at": "2026-10-10T08:00:00Z", "status": "assumed" },
      "confidence": "assumed"
    }
  ],
  "warnings": [
    "Example graph is partial; live discovery must expand oracle, collateral, debt and liquidity dependencies for all positions."
  ]
}
```

Node types: asset, protocol, market, position, oracle, contract, venue, chain, offchain_entity. Confidence: verified, documented, inferred, assumed.

## 11.3 contracts/market_snapshot.json

```json
{
  "schema_version": "1.0",
  "snapshot_id": "snapshot_demo_01",
  "as_of": "2026-10-10T08:00:00Z",
  "chain_id": 1,
  "block_number": null,
  "prices_usd": {
    "USDe": { "value": "1.00", "source_type": "assumed" },
    "USDC": { "value": "1.00", "source_type": "assumed" },
    "sUSDe": { "value": "1.25", "source_type": "derived" },
    "PT-sUSDe": { "value": "0.9616", "source_type": "derived" }
  },
  "exchange_rates": {
    "sUSDe_USDe": { "value": "1.25", "source_type": "assumed" }
  },
  "markets": {
    "aave_01": {
      "liquidation_threshold": "0.85",
      "liquidation_bonus": "0.05",
      "oracle_pass_through": "1.0",
      "oracle_type": "market_price_feed",
      "verified": false,
      "source_type": "assumed"
    },
    "morpho_01": {
      "lltv": "0.915",
      "liquidation_incentive": "0.026",
      "oracle_pass_through": "0.0",
      "oracle_type": "exchange_rate_usde_hardcoded",
      "verified": false,
      "source_type": "assumed"
    },
    "pendle_01": {
      "maturity": "2027-03-25T00:00:00Z",
      "days_to_maturity": "166",
      "pt_implied_apy": "0.09",
      "valuation_method": "implied_apy_discount",
      "verified": false,
      "source_type": "assumed"
    }
  },
  "yields": {
    "ethena_susde_01": { "token_apy": "0.07", "source_type": "assumed" },
    "aave_01": { "collateral_supply_apy": "0.05", "debt_borrow_apy": "0.055", "source_type": "assumed" },
    "morpho_01": { "collateral_supply_apy": "0.00", "debt_borrow_apy": "0.055", "source_type": "assumed" },
    "pendle_01": { "token_apy": "0.09", "source_type": "assumed" }
  },
  "exit_venues": {
    "venue:susde_usdc": { "asset": "sUSDe", "quote_method": "proxy", "effective_depth_usd": "200000000", "fee_rate": "0.001", "gas_usd": "40", "source_type": "assumed" },
    "venue:usde_usdc": { "asset": "USDe", "quote_method": "proxy", "effective_depth_usd": "300000000", "fee_rate": "0.001", "gas_usd": "40", "source_type": "assumed" },
    "venue:pendle_pt_susde": { "asset": "PT-sUSDe", "quote_method": "proxy", "effective_depth_usd": "80000000", "fee_rate": "0.001", "gas_usd": "40", "source_type": "assumed" }
  },
  "warnings": [
    "All values are fixture assumptions, not verified live market parameters.",
    "morpho_01 oracle_pass_through 0.0 is a hypothesis (exchange-rate oracle); P1 must verify the actual oracle."
  ]
}
```

Notes: `markets` and `yields` are keyed by position_id; `exit_venues` by venue id (shared). Morpho collateral earns no supply yield, hence `0.00`. `quote_method` is one of `executable_quote`, `pool_reserves`, `proxy`.

## 11.4 contracts/scenario_request.json — depeg

```json
{
  "schema_version": "1.0",
  "request_id": "sim_001",
  "portfolio_id": "demo_ethena_01",
  "graph_id": "graph_demo_01",
  "snapshot_id": "snapshot_demo_01",
  "scenario": {
    "scenario_id": "usde_depeg",
    "horizon_days": 7,
    "parameters": {
      "usde_spot_shock_pct": "-0.05",
      "susde_market_beta": "1.0",
      "backing_impairment_pct": "0.00",
      "oracle_pass_through_override": null,
      "oracle_lag_hours": "0",
      "pt_pricing_mode": "implied_apy_discount",
      "pt_implied_apy_shock": "0.03"
    }
  },
  "assumptions": {
    "probability": null,
    "source_type": "user_scenario"
  }
}
```

## 11.5 contracts/scenario_request_liquidity.json

```json
{
  "schema_version": "1.0",
  "request_id": "sim_002",
  "portfolio_id": "demo_ethena_01",
  "graph_id": "graph_demo_01",
  "snapshot_id": "snapshot_demo_01",
  "scenario": {
    "scenario_id": "liquidity_crisis",
    "horizon_days": 7,
    "parameters": {
      "exit_liquidity_reduction_pct": "0.80",
      "fundamental_value_shock_pct": "0.00",
      "quote_method": "pool_quote_or_flagged_proxy"
    }
  },
  "assumptions": {
    "probability": null,
    "source_type": "user_scenario"
  }
}
```

## 11.6 contracts/risk_result.json — depeg

Golden values: aave HF 3.0m × 0.85 / 1.8m = 1.4167 → 1.3458; morpho oracle unchanged (pass-through 0) so LTV stays 0.6667 while the mark falls 5%; PT 2.08m × 0.95 / 1.12^(166/365) = 1,876,734.57.

```json
{
  "schema_version": "1.0",
  "simulation_id": "result_sim_001",
  "request_id": "sim_001",
  "portfolio_id": "demo_ethena_01",
  "scenario_id": "usde_depeg",
  "horizon_days": 7,
  "currency": "USD",
  "positions": [
    {
      "position_id": "ethena_susde_01",
      "gross_value_before_usd": "2000000.00",
      "gross_value_after_usd": "1900000.00",
      "executable_value_after_usd": null,
      "debt_after_usd": "0",
      "net_equity_before_usd": "2000000.00",
      "net_equity_after_usd": "1900000.00",
      "conditional_loss_usd": "100000.00",
      "loss_components": { "market_repricing": "100000.00", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "0" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": []
    },
    {
      "position_id": "aave_01",
      "gross_value_before_usd": "3000000.00",
      "gross_value_after_usd": "2850000.00",
      "executable_value_after_usd": null,
      "debt_after_usd": "1800000.00",
      "net_equity_before_usd": "1200000.00",
      "net_equity_after_usd": "1050000.00",
      "conditional_loss_usd": "150000.00",
      "loss_components": { "market_repricing": "150000.00", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "0" },
      "risk_metric": {
        "type": "health_factor",
        "before": "1.4167",
        "after": "1.3458",
        "threshold": "1.0",
        "liquidatable": false,
        "distance_to_liquidation_before_pct": "0.2941",
        "distance_to_liquidation_after_pct": "0.2570"
      },
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Liquidation threshold and oracle response are fixture assumptions."]
    },
    {
      "position_id": "morpho_01",
      "gross_value_before_usd": "3000000.00",
      "gross_value_after_usd": "2850000.00",
      "executable_value_after_usd": null,
      "debt_after_usd": "2000000.00",
      "net_equity_before_usd": "1000000.00",
      "net_equity_after_usd": "850000.00",
      "conditional_loss_usd": "150000.00",
      "loss_components": { "market_repricing": "150000.00", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "0" },
      "risk_metric": {
        "type": "ltv",
        "before": "0.6667",
        "after": "0.6667",
        "threshold": "0.915",
        "liquidatable": false,
        "distance_to_liquidation_before_pct": "0.2714",
        "distance_to_liquidation_after_pct": "0.2714"
      },
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Oracle assumed not to reflect USDe market price (pass-through 0); if it does, LTV rises to 0.7018."]
    },
    {
      "position_id": "pendle_01",
      "gross_value_before_usd": "2000055.14",
      "gross_value_after_usd": "1876734.57",
      "executable_value_after_usd": null,
      "debt_after_usd": "0",
      "net_equity_before_usd": "2000055.14",
      "net_equity_after_usd": "1876734.57",
      "conditional_loss_usd": "123320.57",
      "loss_components": { "market_repricing": "123320.57", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "0" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["PT valued with implied-APY discount approximation."]
    }
  ],
  "portfolio": {
    "net_equity_before_usd": "6200055.14",
    "net_equity_after_usd": "5676734.57",
    "total_conditional_loss_usd": "523320.57",
    "shared_liquidity_penalty_usd": "0",
    "aggregation_status": "complete"
  },
  "provenance": { "model_version": "risk-v0.1", "input_snapshot_id": "snapshot_demo_01", "input_graph_id": "graph_demo_01" },
  "warnings": ["Illustrative output from fixture assumptions; never display as real-market result."]
}
```

## 11.7 contracts/risk_result_liquidity.json — liquidity crisis

Golden values: crisis depth = 20% of effective depth (sUSDe 40m, USDe 60m, PT 16m). Standalone haircut = size² / (D + size). Joint sUSDe venue exit (2.0m + 3.0m = 5.0m): 5² / 45 = 555,555.56 vs 304,540.43 standalone, so the shared-venue penalty is 251,015.13.

```json
{
  "schema_version": "1.0",
  "simulation_id": "result_sim_002",
  "request_id": "sim_002",
  "portfolio_id": "demo_ethena_01",
  "scenario_id": "liquidity_crisis",
  "horizon_days": 7,
  "currency": "USD",
  "positions": [
    {
      "position_id": "ethena_susde_01",
      "gross_value_before_usd": "2000000.00",
      "gross_value_after_usd": "2000000.00",
      "executable_value_after_usd": "1904761.90",
      "debt_after_usd": "0",
      "net_equity_before_usd": "2000000.00",
      "net_equity_after_usd": "1904761.90",
      "conditional_loss_usd": "95238.10",
      "loss_components": { "market_repricing": "0", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "95238.10" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Proxy depth; standalone exit."]
    },
    {
      "position_id": "aave_01",
      "gross_value_before_usd": "3000000.00",
      "gross_value_after_usd": "3000000.00",
      "executable_value_after_usd": "2857142.86",
      "debt_after_usd": "1800000.00",
      "net_equity_before_usd": "1200000.00",
      "net_equity_after_usd": "1057142.86",
      "conditional_loss_usd": "142857.14",
      "loss_components": { "market_repricing": "0", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "142857.14" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Proxy depth; standalone exit."]
    },
    {
      "position_id": "morpho_01",
      "gross_value_before_usd": "3000000.00",
      "gross_value_after_usd": "3000000.00",
      "executable_value_after_usd": "2790697.67",
      "debt_after_usd": "2000000.00",
      "net_equity_before_usd": "1000000.00",
      "net_equity_after_usd": "790697.67",
      "conditional_loss_usd": "209302.33",
      "loss_components": { "market_repricing": "0", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "209302.33" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Proxy depth; standalone exit. Shares venue:susde_usdc with ethena_susde_01."]
    },
    {
      "position_id": "pendle_01",
      "gross_value_before_usd": "2000055.14",
      "gross_value_after_usd": "2000055.14",
      "executable_value_after_usd": "1777821.35",
      "debt_after_usd": "0",
      "net_equity_before_usd": "2000055.14",
      "net_equity_after_usd": "1777821.35",
      "conditional_loss_usd": "222233.79",
      "loss_components": { "market_repricing": "0", "backing_impairment": "0", "liquidation_penalty": "0", "execution_haircut": "222233.79" },
      "risk_metric": null,
      "source_type": "derived",
      "calculation_status": "illustrative",
      "warnings": ["Proxy depth; standalone exit."]
    }
  ],
  "portfolio": {
    "net_equity_before_usd": "6200055.14",
    "net_equity_after_usd": "5279408.65",
    "total_conditional_loss_usd": "920646.49",
    "shared_liquidity_penalty_usd": "251015.13",
    "aggregation_status": "complete"
  },
  "provenance": { "model_version": "risk-v0.1", "input_snapshot_id": "snapshot_demo_01", "input_graph_id": "graph_demo_01" },
  "warnings": ["Portfolio total uses joint exit per shared venue; it exceeds the sum of position losses (669,631.36) by shared_liquidity_penalty_usd."]
}
```

## 11.8 contracts/decision_result.json

Golden values for aave_01 under the depeg: pre-crisis USDe depth 300m, fee 10 bp, gas $40; carry over 7 days = (3.0m × 5% − 1.8m × 5.5%) × 7/365 = 978.08.

```json
{
  "schema_version": "1.0",
  "decision_id": "decision_sim_001",
  "simulation_id": "result_sim_001",
  "portfolio_id": "demo_ethena_01",
  "position_id": "aave_01",
  "scenario_id": "usde_depeg",
  "horizon_days": 7,
  "mode": "conditional_stress",
  "currency": "USD",
  "exit_options": [
    { "exit_fraction": "0.00", "fees_usd": "0", "gas_usd": "0", "price_impact_usd": "0", "estimated_exit_cost_usd": "0", "foregone_yield_usd": "0", "residual_stress_loss_usd": "150000.00", "break_even_probability": null, "objective_usd": null, "quote_status": "proxy" },
    { "exit_fraction": "0.25", "fees_usd": "750.00", "gas_usd": "40.00", "price_impact_usd": "1870.32", "estimated_exit_cost_usd": "2660.32", "foregone_yield_usd": "244.52", "residual_stress_loss_usd": "112500.00", "break_even_probability": "0.0775", "objective_usd": null, "quote_status": "proxy" },
    { "exit_fraction": "0.50", "fees_usd": "1500.00", "gas_usd": "40.00", "price_impact_usd": "7462.69", "estimated_exit_cost_usd": "9002.69", "foregone_yield_usd": "489.04", "residual_stress_loss_usd": "75000.00", "break_even_probability": "0.1266", "objective_usd": null, "quote_status": "proxy" },
    { "exit_fraction": "0.75", "fees_usd": "2250.00", "gas_usd": "40.00", "price_impact_usd": "16749.38", "estimated_exit_cost_usd": "19039.38", "foregone_yield_usd": "733.56", "residual_stress_loss_usd": "37500.00", "break_even_probability": "0.1758", "objective_usd": null, "quote_status": "proxy" },
    { "exit_fraction": "1.00", "fees_usd": "3000.00", "gas_usd": "40.00", "price_impact_usd": "29702.97", "estimated_exit_cost_usd": "32742.97", "foregone_yield_usd": "978.08", "residual_stress_loss_usd": "0", "break_even_probability": "0.2248", "objective_usd": null, "quote_status": "proxy" }
  ],
  "recommendation": "INSUFFICIENT_DATA",
  "recommended_exit_fraction": null,
  "reason": "No scenario probability supplied and all quotes are proxies. Reducing by 25% beats staying if the user's probability of this depeg exceeds 7.75%.",
  "warnings": ["Exit costs use the constant-product proxy on assumed depth; replace with executable quotes."]
}
```

# 12. Validation, tests and demo acceptance

| Area        | Minimum acceptance test                                                                                           |
|-------------|-------------------------------------------------------------------------------------------------------------------|
| Contracts   | Every fixture validates against schema v1; IDs consistent across files; loss_components sum to conditional_loss.  |
| Discovery   | Two different verified markets produce distinct evidence-backed graphs; no hardcoded final graph.                 |
| Risk        | Reproduces the section 11 golden values; USDe shock monotonicity; HF/LLTV formula unit tests; no liquidation without threshold breach; pass-through 0 leaves HF/LTV unchanged. |
| Liquidity   | Larger exit fractions cost more; joint exit on a shared venue ≥ sum of standalone haircuts; missing quotes are flagged. |
| Decision    | Compares 0/25/50/75/100%; reproduces golden break-even probabilities; no unsupported probability or unconditional recommendation. |
| Integration | One click runs both scenarios against same portfolio and returns stable IDs.                                      |
| Demo        | Judges can trace shock → dependency → position impact → exit-cost comparison.                                     |

# 13. Delivery plan and prioritization

| Phase             | P1                             | P2                            | P3                                  | P4                        |
|-------------------|--------------------------------|-------------------------------|-------------------------------------|---------------------------|
| Kickoff           | Freeze identifiers and markets | Freeze scenario semantics     | Freeze cost semantics               | Freeze UI and API schemas |
| Parallel build    | Connect APIs / contracts       | Implement both risk scenarios | Implement quote/proxy and optimizer | Build UI on fixtures      |
| First integration | Publish graph/snapshot JSON    | Consume snapshot JSON         | Consume risk_result JSON            | Connect endpoints         |
| Polish            | Evidence and timestamps        | Unit tests and warnings       | Sensitivity charts                  | Narrated demo and pitch   |

If time is short: prioritize one end-to-end validated market path plus a second distinct position; show both scenarios reliably. Add third and fourth positions only after integration is stable. Reserve a final period for reproducible demo, data refresh and fallback fixtures.

# 14. Known risks, caveats and next actions

- Market availability: verify currently live USDe/sUSDe Aave, Morpho and Pendle markets, exact contract addresses, oracle types and maturities.
- Morpho oracle: the fixture assumes an exchange-rate oracle (pass-through 0). If the live market prices sUSDe from a USDe/USD feed, pass-through becomes 1 and the demo story changes; P1 confirms at kickoff.
- Ethena off-chain dependencies: public disclosure may not expose real-time counterparty exposures; label these documented or assumed.
- Oracle behavior: distinguish spot price shocks from oracle updates and liquidation mechanics.
- Pendle PT pricing: the implied-APY discount is an approximation; it ignores AMM curve dynamics and the SY exchange rate.
- Execution: real quotes may be unavailable or non-executable for the hypothetical portfolio size; the constant-product proxy overstates impact on stableswap pools. Show limitations.
- sUSDe exit: the cooldown-based redemption is not an instant exit; v1 exits through the secondary market only.
- Data freshness: capture timestamps, block numbers and network identifiers, and freeze a reproducible demo snapshot.
- Security: read-only RPC and public APIs; never ask for private keys.

## Immediate team kickoff checklist

- Agree on this v1.1 scope and appoint P1/P2/P3/P4.
- Create repository and copy fixtures from section 11 into contracts/.
- P1 verifies exact live market identifiers, oracle types and replaces placeholders.
- P2 implements deterministic risk calculations on fixtures, reproducing the golden values.
- P3 implements conditional exit comparisons and quote-status handling.
- P4 implements API contracts and frontend against fixtures.
- Schedule a first integration test as soon as each module returns valid JSON.

# 15. Reference documentation to verify during implementation

- Ethena documentation: https://docs.ethena.fi/
- Aave developer documentation: https://aave.com/docs
- Morpho developer documentation: https://docs.morpho.org/
- Pendle developer documentation: https://docs.pendle.finance/
- DefiLlama (supplementary ecosystem context): https://defillama.com/

Reference URLs are starting points, not proof of any particular live market. The implementation must record specific on-chain evidence and observed timestamps.

# 16. Detailed implementation playbook — four parallel modules

This section is the practical assignment sheet for each teammate. All four developers can begin immediately using the versioned sample JSON files in contracts/. Every module must expose a deterministic function or endpoint, ship unit tests, and state which outputs are observed versus assumed.

## P1 — Data & Dependency Discovery

**Mission:** Own the factual foundation: identify real Ethereum markets and build an evidence-backed graph from the hypothetical portfolio.

**Inputs:** contracts/portfolio.json + protocol configuration

**Outputs:** contracts/dependency_graph.json and contracts/market_snapshot.json

### Implementation tasks

1. Implement protocol adapters for Ethena, Aave, Morpho and Pendle. Start with one verified USDe/sUSDe-linked market per integration; store contract address, chain ID, block/time, and source URL.
2. Resolve token identities (USDe, sUSDe, PT and wrapped variants) and normalize decimals, units, price currency and market IDs. Distinguish underlying asset, collateral, debt, oracle, market and exit venue. Read the sUSDe exchange rate on-chain.
3. Extract Aave liquidation thresholds/bonus/oracle settings, Morpho collateral/loan/LLTV/oracle parameters (and oracle type, which sets pass-through), and Pendle PT underlying/maturity/implied APY/pool metadata. Read supply and borrow APYs. Mark unavailable fields explicitly; never fabricate them.
4. Generate typed nodes and directed edges with relation_type, evidence/source, observed_at and confidence. Add an exit venue node per sell route and `exits_via` edges. Separate verified on-chain links from documented off-chain Ethena exposure.
5. Create a reproducible snapshot cache and a fixture-only mode so the rest of the team can work offline.

### Definition of done

Given two distinct market identifiers, the module returns distinct evidence-backed graphs and consistent market snapshots. Every critical edge has a source; missing data is flagged, not silently filled.

## P2 — Quantitative Risk & Propagation

**Mission:** Translate each scenario into position-level and portfolio-level economic consequences, using the dependency graph and market parameters.

**Inputs:** portfolio.json + dependency_graph.json + market_snapshot.json + scenario_request.json

**Outputs:** contracts/risk_result.json and contracts/risk_result_liquidity.json

### Implementation tasks

1. Build a normalized position valuation layer: quantity, mark price (sUSDe via exchange rate, PT via implied-APY discount), debt, collateral, net equity and currency. Ensure the same economic exposure is not counted twice.
2. Implement scenario A (USDe market depeg) with the section 7.1 parameters: market shock, sUSDe beta, backing impairment, per-market oracle pass-through with override, oracle lag. Recompute direct exposure and lending collateral/debt valuations.
3. For Aave calculate health factor using actual market configuration; for Morpho compute LTV/LLTV and liquidation eligibility. Return distance-to-liquidation, not just a Boolean.
4. For Pendle, implement the implied-APY discount PT pricing (section 7.1); label it an approximation until validated.
5. Implement scenario B (liquidity crisis): mark value vs executable value, crisis depth per venue, standalone and joint-exit haircuts, shared_liquidity_penalty_usd. Report loss components and sensitivity ranges.
6. Write unit tests for no-shock invariance, worsening-collateral monotonicity, oracle pass-through 0 vs 1, maturity handling, aggregate reconciliation and the section 11 golden values.

### Definition of done

Both scenarios run on the same portfolio fixture, produce reproducible per-position outputs, and explain every modeled loss and liquidation flag. Scenario loss is never mislabeled as an expected loss without probabilities.

## P3 — Decision, Liquidity & Exit Optimization

**Mission:** Convert risk outputs into financially defensible STAY / REDUCE / EXIT choices with execution frictions and explicit assumptions.

**Inputs:** portfolio.json + market_snapshot.json + risk_result.json + scenario_request.json

**Outputs:** contracts/decision_result.json

### Implementation tasks

1. Apply the section 4.2 and 8 conventions: per-position decisions, horizon from the scenario request, exits at pre-shock prices, candidate exit fractions 0%, 25%, 50%, 75%, 100%.
2. Implement a pluggable execution cost estimator: trading fees, gas and nonlinear price impact, with quote priority executable → pool reserves → proxy (section 7.2). Begin with the constant-product proxy; replace with real venue quotes when available.
3. Calculate conditional residual stress loss after each exit size (pro-rata); avoid comparing certain immediate costs against unweighted scenario losses as though they were probabilities.
4. Compute foregone yield from `market_snapshot.yields` and the break-even probability p*(x) for every option. If probabilities are supplied, calculate J(x) on a consistent horizon.
5. Optimize candidate exit sizes, enforce liquidity and minimum trade constraints, and return ranked alternatives plus the explanation and uncertainty caveats, following the section 8 recommendation rules.
6. Test zero exit, full exit, convex slippage, no-incident case, sensitivity to incident probability, scenarios where partial exit dominates, and the section 11.8 golden values.

### Definition of done

For each position, five exit fractions have transparent costs and residual risks; a chosen action is reproducible and changes sensibly when slippage or risk assumptions change.

## P4 — Frontend, API Orchestration & Demo

**Mission:** Deliver the judge-facing application and integrate the other three modules without blocking on their completion.

**Inputs:** All contracts/\*.json fixtures; later the live module APIs

**Outputs:** Interactive React demo and FastAPI orchestration

### Implementation tasks

1. Create four views: portfolio overview, dependency graph, scenario controls and decision results. Show net equity and gross exposure separately.
2. Build React Flow visualization with node categories, edge evidence drawer, critical path highlighting, shared exit venues, and warnings for inferred/off-chain links.
3. Provide controls for USDe depeg magnitude, oracle pass-through override, oracle lag, liquidity-depth reduction and decision horizon. Use two fixed scenario presets for a reliable demo.
4. Create FastAPI orchestration endpoints that validate schema versions and call P1 → P2 → P3; provide fixture responses (per-module fixture/live switch) while each service is under development.
5. Visualize before/after valuation, distance to liquidation, cost-versus-risk tradeoffs, break-even probabilities and recommended exit fraction. Display data freshness and observed/derived/assumed badges.
6. Prepare a deterministic demo script, loading/error states, one-click reset, and screenshots or a backup recording if external APIs fail.

### Definition of done

A reviewer can load a fictional portfolio, inspect verified dependencies, run either scenario and understand the STAY/REDUCE/EXIT reasoning in under three minutes, including when operating offline.

# 17. Integration rules and ownership boundaries

- P1 owns market facts and provenance; P2 owns valuation and risk semantics; P3 owns execution costs and action selection; P4 owns user-facing presentation and API composition. No module independently changes another module's contract.
- Freeze schema v1 before implementation. All monetary values use USD, all token quantities preserve token decimals, timestamps use ISO 8601 UTC, chain IDs are explicit, and each position has a stable position_id.
- Never mix illustrative portfolio holdings with claims about actual on-chain ownership. Real market parameters must be timestamped. Mock values carry source_type="mock" or equivalent.
- Each person provides a callable entry point, a README with setup instructions, example request/response and at least three unit tests. Merge via pull requests and run end-to-end fixture tests at every integration checkpoint.
- Integration checkpoints: (1) all four fixture modules run; (2) P1 real snapshot flows into P2; (3) P2 outputs feed P3; (4) P4 demonstrates the entire workflow; (5) freeze demo and prepare offline fallback.
