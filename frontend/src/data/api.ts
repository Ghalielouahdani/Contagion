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
export const fixtureRuntimeDiagnostics = {
  viteUseFixtures: import.meta.env.VITE_USE_FIXTURES ?? "(unset)",
  resolvedDefaultMode: defaultDataMode,
  fixtureSet,
  bundledFixtureCount: Object.keys(smallFixtures).length,
  hasRiskSurface: `${FIXTURES}/${fixtureSet}/risk_surface.json` in surfaceLoaders,
};

(globalThis as typeof globalThis & { __DEFI_CONTAGION_DATA__?: typeof fixtureRuntimeDiagnostics }).__DEFI_CONTAGION_DATA__ =
  fixtureRuntimeDiagnostics;
if (typeof document !== "undefined") {
  document.documentElement.dataset.fixturesMode = fixtureRuntimeDiagnostics.resolvedDefaultMode;
  document.documentElement.dataset.fixtureSet = fixtureRuntimeDiagnostics.fixtureSet;
}
console.info("[DeFi Contagion] data source", fixtureRuntimeDiagnostics);

// File suffix per scenario in a fixture set (scenario_request<suffix>.json, risk_result<suffix>.json).
const fileSuffix: Record<ScenarioKind, string> = {
  usde_depeg: "",
  liquidity_crisis: "_liquidity",
  combined_crisis: "_combined",
  governance_change: "_governance",
  carry_squeeze: "_carry",
  node_shock: "_node_shock",
};
const fileByKind = {
  scenario: (kind: ScenarioKind) => `scenario_request${fileSuffix[kind]}.json`,
  risk: (kind: ScenarioKind) => `risk_result${fileSuffix[kind]}.json`,
  decision: (kind: ScenarioKind) => `decision_result${fileSuffix[kind]}.json`,
};

const pct = (value: number) => (value / 100).toFixed(2);

/** Scenario parameters each control drives (the offline surface precomputes only the first one). */
export const scenarioParams: Record<ScenarioKind, Array<{ param: string; value: (inputs: ScenarioInputs) => string }>> = {
  usde_depeg: [{ param: "usde_spot_shock_pct", value: (i) => pct(-i.shockPct) }],
  liquidity_crisis: [{ param: "exit_liquidity_reduction_pct", value: (i) => pct(i.liquidityLossPct) }],
  combined_crisis: [
    { param: "usde_spot_shock_pct", value: (i) => pct(-i.shockPct) },
    { param: "exit_liquidity_reduction_pct", value: (i) => pct(i.liquidityLossPct) },
  ],
  governance_change: [
    { param: "usde_spot_shock_pct", value: (i) => pct(-i.shockPct) },
    { param: "liquidation_threshold_shift", value: (i) => pct(i.ltShiftPct) },
  ],
  carry_squeeze: [
    { param: "borrow_apy_override", value: (i) => pct(i.borrowApyPct) },
    { param: "susde_apy", value: (i) => pct(i.susdeApyPct) },
  ],
  node_shock: [
    { param: "loss_pct", value: (i) => pct(i.nodeLossPct) },
    { param: "node_id", value: (i) => i.nodeId },
  ],
};

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
  const request = JSON.parse(JSON.stringify(baseScenarioRequest(scenario)));
  request.scenario.horizon_days = inputs.horizonDays;
  for (const { param, value } of scenarioParams[scenario]) request.scenario.parameters[param] = value(inputs);
  return request;
}

/** Slider values of a scenario's preset (its fixture request), so picking a preset shows exactly that preset. */
export function presetInputs(scenario: ScenarioKind): Partial<ScenarioInputs> {
  const request = baseScenarioRequest(scenario);
  const p = request.scenario.parameters as Record<string, unknown>;
  const percentOf = (key: string) => (p[key] == null ? undefined : Math.round(Number(p[key]) * 100));
  const inputs: Partial<ScenarioInputs> = { horizonDays: request.scenario.horizon_days };
  const shock = percentOf("usde_spot_shock_pct");
  if (shock !== undefined) inputs.shockPct = Math.abs(shock);
  const liquidity = percentOf("exit_liquidity_reduction_pct");
  if (liquidity !== undefined) inputs.liquidityLossPct = liquidity;
  const ltShift = percentOf("liquidation_threshold_shift");
  if (ltShift !== undefined) inputs.ltShiftPct = ltShift;
  const borrow = percentOf("borrow_apy_override");
  if (borrow !== undefined) inputs.borrowApyPct = borrow;
  const susde = percentOf("susde_apy");
  if (susde !== undefined) inputs.susdeApyPct = susde;
  const loss = percentOf("loss_pct");
  if (loss !== undefined) inputs.nodeLossPct = loss;
  if (typeof p.node_id === "string") inputs.nodeId = p.node_id;
  return inputs;
}

function baseScenarioRequest(scenario: ScenarioKind) {
  return loadFixture(fileByKind.scenario(scenario), () => createMockScenarioRequest(scenario)).data;
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
    ignoredInputs: [],
    analyticsIsPreset: false,
  };
}

async function loadFixtureAppData(scenario: ScenarioKind, inputs: ScenarioInputs): Promise<AppData> {
  const base = buildFixtureAppData(scenario);
  const surface = await loadSurface();
  const points = surface?.scenarios[scenario]?.points;
  if (!points?.length) return base;

  const [live, ...others] = scenarioParams[scenario];
  const target = Number(live.value(inputs));
  const point = points.reduce((best, p) => (Math.abs(Number(p.value) - target) < Math.abs(Number(best.value) - target) ? p : best));
  const risk = withContagion(point.risk_result, base.risk);
  // Offline, only the first parameter is precomputed; say which other inputs are held at the preset.
  const preset = baseScenarioRequest(scenario);
  const ignoredInputs = others
    .filter(({ param, value }) => String((preset.scenario.parameters as Record<string, unknown>)[param]) !== value(inputs))
    .map(({ param }) => param);
  if (inputs.horizonDays !== preset.scenario.horizon_days) ignoredInputs.push("horizon_days");
  const analytics = fixtureAnalytics(scenario, inputs);
  return {
    ...base,
    health: { ...base.health, source: "contracts fixtures · precomputed engine surface" },
    risk,
    decision: normalizeFixtureDecision(point.decisions.aave_01 ?? base.decision, risk),
    decisions: normalizeFixtureDecisions(point.decisions, risk),
    analytics,
    riskSource: "surface",
    ignoredInputs,
    analyticsIsPreset: analytics !== null,
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

/** Offline analytics only exist at the depeg presets (-5% and -30%); never show them for another scenario. */
function fixtureAnalytics(scenario: ScenarioKind, inputs: ScenarioInputs): RiskAnalytics | null {
  if (scenario !== "usde_depeg") return null;
  const preset = loadFixture<RiskAnalytics | null>("risk_analytics.json", () => null).data;
  const severe = loadFixture<RiskAnalytics | null>("risk_analytics_severe.json", () => null).data;
  return severe && inputs.shockPct >= 17.5 ? severe : preset;
}

export const marketSnapshot = buildFixtureAppData("usde_depeg").marketSnapshot;
export const scenarioFixtures = Object.fromEntries(
  (Object.keys(fileSuffix) as ScenarioKind[]).map((kind) => [kind, baseScenarioRequest(kind)]),
) as Record<ScenarioKind, ReturnType<typeof createMockScenarioRequest>>;

export async function postAssistantMessage(request: AssistantRequest, mode: DataMode): Promise<AssistantResponse> {
  const localIntent = parseAssistantIntent(request);
  if (localIntent.actions.length) {
    console.info("[DeFi Contagion] assistant structured actions", localIntent);
    return localIntent;
  }

  try {
    const response = await requestJson<AssistantResponse>(withSet("/api/v1/assistant"), {
      method: "POST",
      body: JSON.stringify({
        message: request.message,
        view: request.view,
        scenario: request.scenario,
        selected_position: request.selectedPosition,
        inspected_exit_fraction: request.inspectedExitFraction,
        scenario_inputs: request.scenarioInputs,
        data: request.data,
        data_mode: mode,
      }),
    });
    console.info("[DeFi Contagion] assistant backend response", response);
    return response;
  } catch (error) {
    console.warn("[DeFi Contagion] assistant backend unavailable; using deterministic browser fallback", error);
  }

  const fallback = fixtureAssistantResponse(request);
  return {
    ...fallback,
    message: `Offline fallback: ${fallback.message}`,
  };
}

function fixtureAssistantResponse(request: AssistantRequest): AssistantResponse {
  // The assistant answers from the results on screen (request.data), never from stored presets.
  return parseAssistantIntent(request);
}

function buildFixtureAppData(scenario: ScenarioKind): AppData {
  const mockedFixtures: string[] = [];
  const portfolio = readFixture<Portfolio>("portfolio.json", () => createMockPortfolio(), mockedFixtures);
  const graph = readFixture<DependencyGraph>("dependency_graph.json", () => createMockDependencyGraph(portfolio), mockedFixtures);
  const marketSnapshot = readFixture<MarketSnapshot>("market_snapshot.json", () => createMockMarketSnapshot(), mockedFixtures);
  const risk = readFixture<RiskResult>(fileByKind.risk(scenario), () => createMockRiskResult(portfolio, scenario), mockedFixtures);
  // Only the depeg has a decision fixture; other scenarios get their decisions from the surface or the API.
  const decisionFixture = loadFixture<DecisionResult>(fileByKind.decision(scenario), () => createMockDecisionResult(risk, scenario));
  if (decisionFixture.mocked) mockedFixtures.push(fileByKind.decision(scenario));
  const decision = normalizeFixtureDecision(decisionFixture.data, risk);

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
    ignoredInputs: [],
    analyticsIsPreset: false,
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

function normalizeFixtureDecisions(decisions: Record<string, DecisionResult>, risk: RiskResult) {
  return Object.fromEntries(Object.entries(decisions).map(([positionId, decision]) => [positionId, normalizeFixtureDecision(decision, risk)]));
}

function normalizeFixtureDecision(decision: DecisionResult, risk: RiskResult): DecisionResult {
  if (decision.recommendation !== "INSUFFICIENT_DATA") return decision;
  const options = decision.exit_options.filter((option) => Number(option.exit_fraction) > 0);
  if (!options.length || !decision.exit_options.some((option) => option.residual_stress_loss_usd != null)) return decision;

  const best = [...options].sort((a, b) => decisionScore(a) - decisionScore(b))[0];
  if (!best) return decision;

  const exitPercent = `${Math.round(Number(best.exit_fraction) * 100)}%`;
  const recommendation = Number(best.exit_fraction) >= 1 ? "EXIT" : "REDUCE";
  const loss = risk.positions.find((position) => position.position_id === decision.position_id)?.conditional_loss_usd;
  const breakEven = best.break_even_probability ? `${(Number(best.break_even_probability) * 100).toFixed(2)}%` : null;
  const reasonParts = [
    `Fixture-derived decision: ${exitPercent} has the strongest break-even profile in the available exit-cost table.`,
    `Immediate cost is $${Number(best.estimated_exit_cost_usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}; residual stress loss is $${Number(best.residual_stress_loss_usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}.`,
  ];
  if (breakEven) reasonParts.push(`Break-even scenario probability is ${breakEven}.`);
  if (loss) reasonParts.push(`Selected-position conditional loss is $${Number(loss).toLocaleString("en-US", { maximumFractionDigits: 0 })}.`);

  return {
    ...decision,
    recommendation,
    recommended_exit_fraction: best.exit_fraction,
    reason: reasonParts.join(" "),
    warnings: [
      ...decision.warnings.filter((warning) => !warning.toLowerCase().includes("no scenario probability")),
      "Offline fixture adapter derived this recommendation from the exit-cost table; no scenario probability was invented.",
    ],
  };
}

function decisionScore(option: DecisionResult["exit_options"][number]) {
  if (option.break_even_probability != null) return Number(option.break_even_probability);
  return Number(option.estimated_exit_cost_usd) + Number(option.residual_stress_loss_usd) + Number(option.foregone_yield_usd);
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
      warnings: [`Mock data: ${fileByKind.risk(scenario)} was generated because the fixture was missing.`],
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
    warnings: [`Mock data: ${fileByKind.risk(scenario)} was generated because the fixture was missing.`],
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
    recommendation: "REDUCE",
    recommended_exit_fraction: "0.25",
    reason: "Mock decision: reducing 25% lowers residual stress while keeping immediate proxy costs below half of the selected position loss.",
    warnings: [`Mock data: ${fileByKind.decision(scenario)} was generated because the fixture was missing.`],
  };
}
