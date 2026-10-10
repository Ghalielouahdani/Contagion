import { parseAssistantIntent } from "../actions/assistantIntent";
import type {
  AppData,
  AssistantRequest,
  AssistantResponse,
  DataMode,
  DecisionResult,
  DependencyGraph,
  MarketSnapshot,
  Portfolio,
  RiskAnalytics,
  RiskResult,
  ScenarioInputs,
  ScenarioKind,
} from "../lib/types";

/**
 * Data layer. Two modes, same AppData:
 * - fixture: offline. Small contract files are bundled; the risk surface (engine results
 *   precomputed for every slider value) is loaded on demand, so sliders stay live offline.
 * - api: the FastAPI backend runs the risk engine on the exact slider values.
 * The fixture set (demo or on-chain verified) comes from VITE_FIXTURE_SET.
 */

const FIXTURES = "../../../contracts/fixtures";
export const fixtureSet: string = import.meta.env.VITE_FIXTURE_SET || "demo_ethena_01";

const smallFixtures = import.meta.glob(["../../../contracts/fixtures/*/*.json", "!**/risk_surface.json"], {
  eager: true,
  import: "default",
}) as Record<string, unknown>;
const surfaceLoaders = import.meta.glob("../../../contracts/fixtures/*/risk_surface.json", { import: "default" }) as Record<
  string,
  () => Promise<unknown>
>;

export const defaultDataMode: DataMode = readFixtureDefault() ? "fixture" : "api";

const fileByKind = {
  scenario: { usde_depeg: "scenario_request.json", liquidity_crisis: "scenario_request_liquidity.json" },
  risk: { usde_depeg: "risk_result.json", liquidity_crisis: "risk_result_liquidity.json" },
  decision: { usde_depeg: "decision_result.json", liquidity_crisis: "decision_result_liquidity.json" },
} as const;

type SurfacePoint = { value: string; risk_result: RiskResult; decisions: Record<string, DecisionResult> };
type RiskSurface = { scenarios: Record<string, { param: string; points: SurfacePoint[] }> };

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

const withSet = (path: string) => `${path}?set=${encodeURIComponent(fixtureSet)}`;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

/** The set's scenario request with the slider values applied (decimal strings, as the contract requires). */
export function buildScenarioRequest(scenario: ScenarioKind, inputs: ScenarioInputs) {
  const base = loadFixture(fileByKind.scenario[scenario], () => createMockScenarioRequest(scenario)).data;
  const request = JSON.parse(JSON.stringify(base));
  request.scenario.horizon_days = inputs.horizonDays;
  if (scenario === "usde_depeg") request.scenario.parameters.usde_spot_shock_pct = (-inputs.shockPct / 100).toFixed(2);
  else request.scenario.parameters.exit_liquidity_reduction_pct = (inputs.liquidityLossPct / 100).toFixed(2);
  return request;
}

export async function loadAppData(mode: DataMode, scenario: ScenarioKind, inputs: ScenarioInputs): Promise<AppData> {
  if (mode === "fixture") return loadFixtureAppData(scenario, inputs);

  const request = buildScenarioRequest(scenario, inputs);
  const [health, portfolio, graph, marketSnapshot, risk, analytics] = await Promise.all([
    requestJson<{ status: string; fixture_set?: string }>(withSet("/api/v1/health")),
    requestJson<Portfolio>(withSet("/api/v1/portfolio")),
    requestJson<DependencyGraph>(withSet("/api/v1/discover"), post({ schema_version: "1.0" })),
    requestJson<MarketSnapshot>(withSet("/api/v1/market-snapshot")),
    requestJson<RiskResult>(withSet("/api/v1/simulate"), post(request)),
    requestJson<RiskAnalytics>(withSet("/api/v1/analyze"), post(request)),
  ]);
  const decisionList = await Promise.all(
    portfolio.positions.map((position) =>
      requestJson<DecisionResult>(withSet("/api/v1/decide"), post({ request, position_id: position.position_id })),
    ),
  );
  const decisions = Object.fromEntries(decisionList.map((decision) => [decision.position_id, decision]));

  return {
    health: { status: health.status, mode: "api", source: "FastAPI · live risk engine", mockedFixtures: [], fixtureSet: health.fixture_set ?? fixtureSet },
    portfolio,
    graph,
    marketSnapshot,
    risk,
    decision: decisions.aave_01 ?? decisionList[0],
    decisions,
    analytics,
    riskSource: "engine",
  };
}

async function loadFixtureAppData(scenario: ScenarioKind, inputs: ScenarioInputs): Promise<AppData> {
  const base = buildFixtureAppData(scenario);
  const surface = await loadSurface();
  const points = surface?.scenarios[scenario]?.points;
  if (!points?.length) return base;

  const target = scenario === "usde_depeg" ? -inputs.shockPct / 100 : inputs.liquidityLossPct / 100;
  const point = points.reduce((best, p) => (Math.abs(Number(p.value) - target) < Math.abs(Number(best.value) - target) ? p : best));
  const risk = withContagion(point.risk_result, base.risk);
  return {
    ...base,
    health: { ...base.health, source: "contracts fixtures · precomputed engine surface" },
    risk,
    decision: point.decisions.aave_01 ?? base.decision,
    decisions: point.decisions,
    analytics: fixtureAnalytics(scenario, inputs),
    riskSource: "surface",
  };
}

let surfaceCache: Promise<RiskSurface | null> | null = null;
function loadSurface(): Promise<RiskSurface | null> {
  const loader = surfaceLoaders[`${FIXTURES}/${fixtureSet}/risk_surface.json`];
  if (!loader) return Promise.resolve(null);
  surfaceCache ??= loader().then((data) => data as RiskSurface).catch(() => null);
  return surfaceCache;
}

/** Surface points omit contagion paths (they do not depend on the slider); take them from the set's risk result. */
function withContagion(result: RiskResult, reference: RiskResult): RiskResult {
  const paths = new Map(reference.positions.map((position) => [position.position_id, position.contagion]));
  return {
    ...result,
    contagion: reference.contagion,
    positions: result.positions.map((position) => ({ ...position, contagion: paths.get(position.position_id) })),
  };
}

/** Offline analytics only exist at the presets (-5% and -30% depeg); pick the closest. */
function fixtureAnalytics(scenario: ScenarioKind, inputs: ScenarioInputs): RiskAnalytics | null {
  const preset = loadFixture<RiskAnalytics | null>("risk_analytics.json", () => null).data;
  const severe = loadFixture<RiskAnalytics | null>("risk_analytics_severe.json", () => null).data;
  if (scenario === "usde_depeg" && severe && inputs.shockPct >= 17.5) return severe;
  return preset;
}

export const marketSnapshot = buildFixtureAppData("usde_depeg").marketSnapshot;
export const scenarioFixtures = {
  usde_depeg: loadFixture(fileByKind.scenario.usde_depeg, () => createMockScenarioRequest("usde_depeg")).data,
  liquidity_crisis: loadFixture(fileByKind.scenario.liquidity_crisis, () => createMockScenarioRequest("liquidity_crisis")).data,
};

export async function postAssistantMessage(request: AssistantRequest, mode: DataMode): Promise<AssistantResponse> {
  if (mode === "api") {
    try {
      return await requestJson<AssistantResponse>("/api/v1/assistant", {
        method: "POST",
        body: JSON.stringify({
          message: request.message,
          view: request.view,
          scenario: request.scenario,
          selected_position: request.selectedPosition,
          inspected_exit_fraction: request.inspectedExitFraction,
          scenario_inputs: request.scenarioInputs,
        }),
      });
    } catch {
      // No server-side assistant yet (the API answers 501): fall back to the local intent parser.
    }
  }

  return fixtureAssistantResponse(request);
}

function fixtureAssistantResponse(request: AssistantRequest): AssistantResponse {
  return parseAssistantIntent({
    ...request,
    scenarioDataByKind: {
      usde_depeg: buildFixtureAppData("usde_depeg"),
      liquidity_crisis: buildFixtureAppData("liquidity_crisis"),
    },
  });
}

function buildFixtureAppData(scenario: ScenarioKind): AppData {
  const mockedFixtures: string[] = [];
  const portfolio = readFixture<Portfolio>("portfolio.json", () => createMockPortfolio(), mockedFixtures);
  const graph = readFixture<DependencyGraph>("dependency_graph.json", () => createMockDependencyGraph(portfolio), mockedFixtures);
  const marketSnapshot = readFixture<MarketSnapshot>("market_snapshot.json", () => createMockMarketSnapshot(), mockedFixtures);
  const risk = readFixture<RiskResult>(fileByKind.risk[scenario], () => createMockRiskResult(portfolio, scenario), mockedFixtures);
  const decision = readFixture<DecisionResult>(fileByKind.decision[scenario], () => createMockDecisionResult(risk, scenario), mockedFixtures);

  return {
    health: { status: "ok", mode: "fixture", source: "contracts fixtures", mockedFixtures, fixtureSet },
    portfolio,
    graph,
    marketSnapshot,
    risk,
    decision,
    decisions: { [decision.position_id]: decision },
    analytics: null,
    riskSource: "fixture",
  };
}

function readFixture<T>(fileName: string, fallback: () => T, mockedFixtures: string[]) {
  const fixture = loadFixture(fileName, fallback);
  if (fixture.mocked) mockedFixtures.push(fileName);
  return fixture.data;
}

function loadFixture<T>(fileName: string, fallback: () => T): { data: T; mocked: boolean } {
  const data = smallFixtures[`${FIXTURES}/${fixtureSet}/${fileName}`] as T | undefined;
  if (data !== undefined) return { data, mocked: false };
  return { data: fallback(), mocked: true };
}

function readFixtureDefault() {
  const value = import.meta.env.VITE_USE_FIXTURES;
  if (value == null || value === "") return true;
  return !["0", "false", "off", "api"].includes(String(value).toLowerCase());
}

function createMockPortfolio(): Portfolio {
  return {
    schema_version: "1.0",
    portfolio_id: "mock_ethena_01",
    as_of: "2026-10-10T08:00:00Z",
    quote_currency: "USD",
    positions: [
      {
        position_id: "aave_01",
        protocol: "aave",
        chain_id: 1,
        position_type: "collateralized_borrow",
        market_id: "MOCK_AAVE_MARKET",
        collateral_asset: "USDe",
        debt_asset: "USDC",
        gross_value_usd: "3000000.00",
        debt_value_usd: "1800000.00",
        net_equity_usd: "1200000.00",
        exit_venue_id: "venue:usde_usdc",
        data_origin: "mock",
      },
      {
        position_id: "ethena_susde_01",
        protocol: "ethena",
        chain_id: 1,
        position_type: "token_holding",
        market_id: null,
        asset_symbol: "sUSDe",
        gross_value_usd: "2000000.00",
        debt_value_usd: "0",
        net_equity_usd: "2000000.00",
        exit_venue_id: "venue:susde_usdc",
        data_origin: "mock",
      },
    ],
    totals: {
      gross_value_usd: "5000000.00",
      debt_value_usd: "1800000.00",
      net_equity_usd: "3200000.00",
    },
  };
}

function createMockDependencyGraph(portfolio: Portfolio): DependencyGraph {
  const positionNodes = portfolio.positions.map((position) => ({
    id: `position:${position.position_id}`,
    type: "position",
    label: `${position.protocol} mock position`,
  }));
  return {
    schema_version: "1.0",
    graph_id: "mock_graph_01",
    portfolio_id: portfolio.portfolio_id,
    as_of: portfolio.as_of,
    nodes: [
      { id: "asset:USDe", type: "asset", label: "USDe" },
      { id: "asset:sUSDe", type: "asset", label: "sUSDe" },
      { id: "protocol:ethena", type: "protocol", label: "Ethena" },
      { id: "venue:susde_usdc", type: "venue", label: "Mock sUSDe/USDC venue" },
      ...positionNodes,
    ],
    edges: positionNodes.map((node, index) => ({
      id: `mock-edge:${index + 1}`,
      source: node.id,
      target: "asset:USDe",
      relation: "exposed_to",
      risk_channel: "mock_dependency",
      confidence: "assumed",
      evidence: {
        method: "generated_mock",
        reference: "contracts fixture fallback",
        observed_at: portfolio.as_of,
        status: "mock",
      },
    })),
    warnings: ["Mock data: dependency_graph.json was generated because the fixture was missing."],
  };
}

function createMockMarketSnapshot(): MarketSnapshot {
  return {
    schema_version: "1.0",
    snapshot_id: "mock_snapshot_01",
    as_of: "2026-10-10T08:00:00Z",
    chain_id: 1,
    prices_usd: {
      USDe: { value: "1.00", source_type: "mock" },
      USDC: { value: "1.00", source_type: "mock" },
      sUSDe: { value: "1.25", source_type: "mock" },
    },
    exchange_rates: {
      sUSDe_USDe: { value: "1.25", source_type: "mock" },
    },
    markets: {},
    yields: {},
    exit_venues: {},
    warnings: ["Mock data: market_snapshot.json was generated because the fixture was missing."],
  };
}

function createMockScenarioRequest(scenario: ScenarioKind) {
  return {
    schema_version: "1.0",
    request_id: scenario === "usde_depeg" ? "mock_sim_001" : "mock_sim_002",
    portfolio_id: "mock_ethena_01",
    graph_id: "mock_graph_01",
    snapshot_id: "mock_snapshot_01",
    scenario: {
      scenario_id: scenario,
      horizon_days: 7,
      parameters:
        scenario === "usde_depeg"
          ? { usde_spot_shock_pct: "-0.05", susde_market_beta: "1.0", backing_impairment_pct: "0.00" }
          : { exit_liquidity_reduction_pct: "0.80", fundamental_value_shock_pct: "0.00", quote_method: "generated_mock" },
    },
    assumptions: { probability: null, source_type: "mock" },
  };
}

function createMockRiskResult(portfolio: Portfolio, scenario: ScenarioKind): RiskResult {
  const multiplier = scenario === "usde_depeg" ? 0.05 : 0.08;
  const positions = portfolio.positions.map((position) => {
    const gross = Number(position.gross_value_usd);
    const debt = Number(position.debt_value_usd);
    const loss = gross * multiplier;
    const afterGross = gross - loss;
    const afterEquity = afterGross - debt;
    return {
      position_id: position.position_id,
      gross_value_before_usd: gross.toFixed(2),
      gross_value_after_usd: afterGross.toFixed(2),
      executable_value_after_usd: scenario === "liquidity_crisis" ? (afterGross * 0.96).toFixed(2) : null,
      debt_after_usd: debt.toFixed(2),
      net_equity_before_usd: Number(position.net_equity_usd).toFixed(2),
      net_equity_after_usd: afterEquity.toFixed(2),
      conditional_loss_usd: loss.toFixed(2),
      loss_components: {
        market_repricing: scenario === "usde_depeg" ? loss.toFixed(2) : "0",
        backing_impairment: "0",
        liquidation_penalty: "0",
        execution_haircut: scenario === "liquidity_crisis" ? loss.toFixed(2) : "0",
      },
      risk_metric: null,
      source_type: "mock",
      calculation_status: "mock",
      warnings: [`Mock data: ${fileByKind.risk[scenario]} was generated because the fixture was missing.`],
    };
  });
  const total = positions.reduce((sum, position) => sum + Number(position.conditional_loss_usd), 0);
  return {
    schema_version: "1.0",
    simulation_id: scenario === "usde_depeg" ? "mock_result_001" : "mock_result_002",
    request_id: scenario === "usde_depeg" ? "mock_sim_001" : "mock_sim_002",
    portfolio_id: portfolio.portfolio_id,
    scenario_id: scenario,
    horizon_days: 7,
    currency: "USD",
    positions,
    portfolio: {
      total_conditional_loss_usd: total.toFixed(2),
      shared_liquidity_penalty_usd: scenario === "liquidity_crisis" ? (total * 0.12).toFixed(2) : "0",
      aggregation_status: "mock",
    },
    warnings: [`Mock data: ${fileByKind.risk[scenario]} was generated because the fixture was missing.`],
  };
}

function createMockDecisionResult(risk: RiskResult, scenario: ScenarioKind): DecisionResult {
  const selectedRisk = risk.positions.find((position) => position.position_id === "aave_01") ?? risk.positions[0];
  const stressLoss = Number(selectedRisk?.conditional_loss_usd ?? risk.portfolio.total_conditional_loss_usd);
  const exitOptions = ["0.00", "0.25", "0.50", "0.75", "1.00"].map((fraction) => {
    const amount = Number(fraction);
    const priceImpact = stressLoss * amount * amount * 0.18;
    const fees = stressLoss * amount * 0.01;
    const gas = amount === 0 ? 0 : 40;
    return {
      exit_fraction: fraction,
      fees_usd: fees.toFixed(2),
      gas_usd: gas.toFixed(2),
      price_impact_usd: priceImpact.toFixed(2),
      estimated_exit_cost_usd: (fees + gas + priceImpact).toFixed(2),
      foregone_yield_usd: (stressLoss * amount * 0.0065).toFixed(2),
      residual_stress_loss_usd: (stressLoss * (1 - amount)).toFixed(2),
      break_even_probability: amount === 0 ? null : Math.min(0.95, (fees + gas + priceImpact) / Math.max(stressLoss * amount, 1)).toFixed(4),
      objective_usd: null,
      quote_status: "mock",
    };
  });

  return {
    schema_version: "1.0",
    decision_id: scenario === "usde_depeg" ? "mock_decision_001" : "mock_decision_002",
    simulation_id: risk.simulation_id,
    portfolio_id: risk.portfolio_id,
    position_id: selectedRisk?.position_id ?? "aave_01",
    scenario_id: scenario,
    horizon_days: risk.horizon_days,
    mode: "conditional_stress",
    currency: risk.currency,
    exit_options: exitOptions,
    recommendation: scenario === "liquidity_crisis" ? "REDUCE" : "INSUFFICIENT_DATA",
    recommended_exit_fraction: scenario === "liquidity_crisis" ? "0.25" : null,
    reason:
      scenario === "liquidity_crisis"
        ? "Mock decision: reducing 25% lowers residual stress while keeping immediate proxy costs below half of the selected position loss."
        : "Mock decision: no scenario probability supplied, so the app shows break-even thresholds instead of inventing a conviction.",
    warnings: [`Mock data: ${fileByKind.decision[scenario]} was generated because the fixture was missing.`],
  };
}
