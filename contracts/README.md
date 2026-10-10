# contracts/ — schema v1 integration contract (shared by everyone)

This folder is how the four modules talk to each other. Each module reads JSON in these shapes and writes JSON in these shapes. As long as everyone respects them, P1–P4 can work in parallel without waiting for each other.

**This folder is the source of truth.** Blueprint section 11 shows the same fixtures for reading; if they ever differ, `contracts/` wins.

Read: blueprint sections 4.2 (conventions), 9.1 (parallelism), 11 (fixtures), 17 (ownership).

## Structure

```
contracts/
├── schemas/v1/                         JSON Schema (draft 2020-12), language-agnostic
│   ├── common.schema.json              shared types + vocabularies (protocols, relations, source types…)
│   ├── portfolio.schema.json           ┐
│   ├── dependency_graph.schema.json    │
│   ├── market_snapshot.schema.json     │ one schema per contract file
│   ├── scenario_request.schema.json    │ (they assemble the plug-ins below)
│   ├── risk_result.schema.json         │
│   ├── decision_result.schema.json     ┘
│   ├── fixture_set.schema.json         manifest of a fixture set
│   ├── positions/      token_holding · collateralized_borrow · pt_holding
│   ├── markets/        aave_v3_reserve · morpho_blue_market · pendle_pt_market
│   ├── scenarios/      usde_depeg · liquidity_crisis
│   └── risk_metrics/   health_factor · ltv
└── fixtures/
    ├── demo_ethena_01/                 one self-consistent data set (golden, assumed values)
    │   ├── manifest.json               ids + which file uses which schema
    │   ├── portfolio.json · dependency_graph.json · market_snapshot.json
    │   ├── scenario_request.json · scenario_request_liquidity.json
    │   └── risk_result.json · risk_result_liquidity.json · decision_result.json
    └── live_ethena_01/                 same 4 positions discovered on real markets by P1 (not golden)
        └── portfolio.json · dependency_graph.json · market_snapshot.json · scenario_request*.json
```

P1's live discovery adds optional fields (additive, still `1.0`): graph `chain_id`, `block_number`,
`coverage` (five dependency layers per position), `unresolved`, `discovery`; evidence `call` and `note`;
snapshot `exit_venues.*.quotes` and `markets.*.details`. See `backend/discovery/README.md`.

## Why it is modular

Each varying part is a **plug-in file**, chosen by a discriminator field:

| What varies       | Discriminator field                 | Plug-in folder         | Registered in                                   |
|-------------------|-------------------------------------|------------------------|-------------------------------------------------|
| Position type     | `position_type`                     | `positions/`           | `portfolio.schema.json` → `$defs.position.oneOf` |
| Protocol market   | `market_kind`                       | `markets/`             | `market_snapshot.schema.json` → `$defs.market.oneOf` |
| Scenario          | `scenario_id`                       | `scenarios/`           | `scenario_request.schema.json` → `$defs.scenario.oneOf` + `common` `scenario_id` |
| Risk metric       | `type`                              | `risk_metrics/`        | `risk_result.schema.json` → `$defs.risk_metric.oneOf` |
| Vocabularies      | —                                   | `common.schema.json`   | add a value to the enum (protocol, relation, risk_channel, node_type…) |
| Loss component    | —                                   | —                      | open: just add a key (the core four stay required) |
| Demo data set     | `fixture_set_id`                    | `fixtures/<set>/`      | its own `manifest.json`                          |

Shared fields live once in `common.schema.json` (`position_base`, `market_base`, `risk_metric_base`); a plug-in only declares what is specific to it. Plug-ins are strict: unknown fields are rejected, which catches typos.

## How to extend (recipes)

**Add a protocol** (e.g. Curve):
1. Add `"curve"` to `protocol` in `common.schema.json`.
2. If it has market parameters, create `markets/curve_pool.schema.json` (copy an existing one: `allOf` → `market_base`, `market_kind` const, its own fields, `unevaluatedProperties: false`).
3. Add it to `$defs.market.oneOf` in `market_snapshot.schema.json`.
4. P1 writes the matching adapter.

**Add a position type** (e.g. `lp_position`): create `positions/lp_position.schema.json` (`allOf` → `position_base`), then add it to `$defs.position.oneOf` in `portfolio.schema.json`.

**Add a scenario** (e.g. `oracle_freeze`):
1. Create `scenarios/oracle_freeze.schema.json` with `scenario_id` const and its `parameters`.
2. Add it to `$defs.scenario.oneOf` in `scenario_request.schema.json`, and add `"oracle_freeze"` to `scenario_id` in `common.schema.json`.
3. Add a fixture request (and golden result) in a fixture set.

**Add a risk metric**: create `risk_metrics/<type>.schema.json` (`allOf` → `risk_metric_base`), then add it to `$defs.risk_metric.oneOf` in `risk_result.schema.json`.

**Add a demo data set**: create `fixtures/<new_set>/` with its own `manifest.json`. Existing sets are untouched.

## Versioning rules

- **Additive changes** (new plug-in, new enum value, new optional field) keep `schema_version: "1.0"`.
- **Breaking changes** (rename, remove or retype a field, make a field required) create `schemas/v2/` and bump `schema_version`. v1 stays until every module has migrated.
- Changes go through the owner of the contract file (portfolio/graph/snapshot → P1, scenario semantics/risk_result → P2, decision_result → P3, API envelopes → P4), in one PR that updates the schema, the fixtures and blueprint section 11.

## Data conventions (enforced by the schemas)

- `schema_version` is `"1.0"`; IDs are lowercase slugs; node IDs are `<type>:<name>` (e.g. `venue:susde_usdc`).
- Numbers are **strings** (`"1800000"`, `"-0.05"`), never JSON floats. Values are in USD, rates are decimal fractions, timestamps are UTC with a `Z` suffix.
- Losses and costs are **positive**; shocks are **signed**.
- Every object with numbers carries `source_type`; `field_sources` overrides it per field when an object mixes origins.
- Placeholders (`TO_VERIFY_...`) stay visible until P1 replaces them with verified values.

## Golden fixtures

`demo_ethena_01` has `"golden": true`: its risk and decision files are the **exact** outputs the section 7–8 formulas must produce from its portfolio and snapshot. P2 and P3 use them as test expectations. Beyond schema validity, they satisfy:
- `loss_components` sum to `conditional_loss_usd`; net equity before − loss = net equity after;
- positions sum to the portfolio total (+ `shared_liquidity_penalty_usd` in the liquidity scenario);
- IDs are consistent across all files of the set.

## Using the schemas in code

Generate types instead of rewriting them by hand: Python Pydantic v2 models with `datamodel-code-generator`, TypeScript types with `json-schema-to-typescript`. Validate at runtime with `jsonschema` (Python) or `ajv` (TypeScript).
