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
  RiskResult,
  ScenarioKind,
} from "../lib/types";

const FIXTURE_ROOT = "../../../contracts/fixtures/demo_ethena_01";
const fixtureModules = import.meta.glob("../../../contracts/fixtures/demo_ethena_01/*.json", { eager: true }) as Record<string, { default?: unknown } | unknown>;

export const defaultDataMode: DataMode = readFixtureDefault() ? "fixture" : "api";

const fixtureFileNames = {
  portfolio: "portfolio.json",
  graph: "dependency_graph.json",
  marketSnapshot: "market_snapshot.json",
  scenarioDepeg: "scenario_request.json",
  scenarioLiquidity: "scenario_request_liquidity.json",
  riskDepeg: "risk_result.json",
  riskLiquidity: "risk_result_liquidity.json",
  decisionDepeg: "decision_result.json",
  decisionLiquidity: "decision_result_liquidity.json",
};

const scenarioFileByKind: Record<ScenarioKind, string> = {
  usde_depeg: fixtureFileNames.scenarioDepeg,
  liquidity_crisis: fixtureFileNames.scenarioLiquidity,
};

const riskFileByKind: Record<ScenarioKind, string> = {
  usde_depeg: fixtureFileNames.riskDepeg,
  liquidity_crisis: fixtureFileNames.riskLiquidity,
};

const decisionFileByKind: Record<ScenarioKind, string> = {
  usde_depeg: fixtureFileNames.decisionDepeg,
  liquidity_crisis: fixtureFileNames.decisionLiquidity,
};

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

export async function loadAppData(mode: DataMode, scenario: ScenarioKind): Promise<AppData> {
  if (mode === "fixture") return buildFixtureAppData(scenario);

  const health = await requestJson<{ status: string; mode?: DataMode }>("/api/v1/health");
  const portfolio = await requestJson<Portfolio>("/api/v1/portfolio");
  const graph = await requestJson<DependencyGraph>("/api/v1/discover", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0", portfolio_id: portfolio.portfolio_id }),
  });
  const scenarioRequest = loadFixture(scenarioFileByKind[scenario], () => createMockScenarioRequest(scenario)).data;
  const risk = await requestJson<RiskResult>("/api/v1/simulate", {
    method: "POST",
    body: JSON.stringify(scenarioRequest),
  });
  const decision = await requestJson<DecisionResult>("/api/v1/decide", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.0",
      portfolio_id: portfolio.portfolio_id,
      simulation_id: risk.simulation_id,
      position_id: "aave_01",
    }),
  });
  const marketSnapshot = await requestJson<MarketSnapshot>("/api/v1/market-snapshot");

  return {
    health: { status: health.status, mode: "api", source: "FastAPI", mockedFixtures: [] },
    portfolio,
    graph,
    marketSnapshot,
    risk,
    decision,
  };
}

export const marketSnapshot = buildFixtureAppData("usde_depeg").marketSnapshot;
export const scenarioFixtures = {
  usde_depeg: loadFixture(scenarioFileByKind.usde_depeg, () => createMockScenarioRequest("usde_depeg")).data,
  liquidity_crisis: loadFixture(scenarioFileByKind.liquidity_crisis, () => createMockScenarioRequest("liquidity_crisis")).data,
};

export async function postAssistantMessage(request: AssistantRequest, mode: DataMode): Promise<AssistantResponse> {
  if (mode === "api") {
    return requestJson<AssistantResponse>("/api/v1/assistant", {
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
  const portfolio = readFixture<Portfolio>(fixtureFileNames.portfolio, () => createMockPortfolio(), mockedFixtures);
  const graph = readFixture<DependencyGraph>(fixtureFileNames.graph, () => createMockDependencyGraph(portfolio), mockedFixtures);
  const marketSnapshot = readFixture<MarketSnapshot>(fixtureFileNames.marketSnapshot, () => createMockMarketSnapshot(), mockedFixtures);
  const risk = readFixture<RiskResult>(riskFileByKind[scenario], () => createMockRiskResult(portfolio, scenario), mockedFixtures);
  const decision = readFixture<DecisionResult>(decisionFileByKind[scenario], () => createMockDecisionResult(risk, scenario), mockedFixtures);

  return {
    health: { status: "ok", mode: "fixture", source: "contracts fixtures", mockedFixtures },
    portfolio,
    graph,
    marketSnapshot,
    risk,
    decision,
  };
}

function readFixture<T>(fileName: string, fallback: () => T, mockedFixtures: string[]) {
  const fixture = loadFixture(fileName, fallback);
  if (fixture.mocked) mockedFixtures.push(fileName);
  return fixture.data;
}

function loadFixture<T>(fileName: string, fallback: () => T): { data: T; mocked: boolean } {
  const module = fixtureModules[`${FIXTURE_ROOT}/${fileName}`] as { default?: T } | T | undefined;
  if (module) return { data: ("default" in Object(module) ? (module as { default: T }).default : module) as T, mocked: false };
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
      warnings: [`Mock data: ${riskFileByKind[scenario]} was generated because the fixture was missing.`],
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
    warnings: [`Mock data: ${riskFileByKind[scenario]} was generated because the fixture was missing.`],
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
    warnings: [`Mock data: ${decisionFileByKind[scenario]} was generated because the fixture was missing.`],
  };
}
