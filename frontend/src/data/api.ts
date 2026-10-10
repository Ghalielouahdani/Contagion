import { proposeScenario } from "../actions/scenarioDraft";
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
export const defaultFixtureSet: string = import.meta.env.VITE_FIXTURE_SET || "stress_portfolio_01";

const smallFixtures = import.meta.glob(["../../../contracts/fixtures/*/*.json", "!**/risk_surface.json"], {
  eager: true,
  import: "default",
}) as Record<string, unknown>;
const surfaceLoaders = import.meta.glob("../../../contracts/fixtures/*/risk_surface.json", { import: "default" }) as Record<
  string,
  () => Promise<unknown>
>;

export const defaultDataMode: DataMode = readFixtureDefault() ? "fixture" : "api";

export type PortfolioData = Pick<AppData, "portfolio" | "graph" | "marketSnapshot">;

/** The original portfolio is fetched independently from submitted stress runs. */
export async function loadPortfolioData(mode: DataMode, set: string): Promise<PortfolioData> {
  if (mode === "api") return requestJson<PortfolioData>(withSet("/api/v1/portfolio-baseline", set));
  return {
    portfolio: readFixture<Portfolio>(set, "portfolio.json"),
    graph: readFixture<DependencyGraph>(set, "dependency_graph.json"),
    marketSnapshot: readFixture<MarketSnapshot>(set, "market_snapshot.json"),
  };
}

/** Fixture sets bundled with the app (each contracts/fixtures/<set>/ with a manifest). */
export const fixtureSets: Array<{ id: string; description: string }> = Object.entries(smallFixtures)
  .filter(([path]) => path.endsWith("/manifest.json"))
  .map(([, manifest]) => {
    const m = manifest as { fixture_set_id: string; description?: string };
    return { id: m.fixture_set_id, description: m.description ?? "" };
  })
  .sort((a, b) => a.id.localeCompare(b.id));

/** Only expose presets with both a request and a computed result in the selected set. */
export function availableScenarios(set: string): ScenarioKind[] {
  return (Object.keys(fileSuffix) as ScenarioKind[]).filter((kind) =>
    `${FIXTURES}/${set}/${fileByKind.scenario(kind)}` in smallFixtures &&
    `${FIXTURES}/${set}/${fileByKind.risk(kind)}` in smallFixtures,
  );
}

// File suffix per scenario in a fixture set (scenario_request<suffix>.json, risk_result<suffix>.json).
const fileSuffix: Record<ScenarioKind, string> = {
  usde_depeg: "",
  liquidity_crisis: "_liquidity",
  combined_crisis: "_combined",
  governance_change: "_governance",
  carry_squeeze: "_carry",
  node_shock: "_node_shock",
  liquidation_cascade: "_cascade",
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
  liquidation_cascade: [
    { param: "usde_spot_shock_pct", value: (i) => pct(-i.shockPct) },
    { param: "exit_liquidity_reduction_pct", value: (i) => pct(i.liquidityLossPct) },
  ],
};

// API mode: which graph and snapshot the backend computes on (see backend/api/discovery_state.py).
const discoveryMode = import.meta.env.VITE_DISCOVERY || "stored";

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

const withSet = (path: string, set: string) => `${path}?set=${encodeURIComponent(set)}`;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

/** The set's scenario request with the slider values applied (decimal strings, as the contract requires). */
export function buildScenarioRequest(scenario: ScenarioKind, inputs: ScenarioInputs, set: string) {
  const request = JSON.parse(JSON.stringify(baseScenarioRequest(scenario, set)));
  request.request_id = `sim_ui_${crypto.randomUUID().replaceAll("-", "_")}`;
  request.scenario.horizon_days = inputs.horizonDays;
  for (const { param, value } of scenarioParams[scenario]) request.scenario.parameters[param] = value(inputs);
  return request;
}

/** Slider values of a scenario's preset (its fixture request), so picking a preset shows exactly that preset. */
export function presetInputs(scenario: ScenarioKind, set: string): Partial<ScenarioInputs> {
  const request = baseScenarioRequest(scenario, set);
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

function baseScenarioRequest(scenario: ScenarioKind, set: string) {
  const request = smallFixtures[`${FIXTURES}/${set}/${fileByKind.scenario(scenario)}`];
  if (!request) throw new Error(`Scenario ${scenario} is unavailable in ${set}`);
  return request as {
    schema_version: string; request_id: string; portfolio_id: string; graph_id: string; snapshot_id: string;
    scenario: { scenario_id: ScenarioKind; horizon_days: number; parameters: Record<string, unknown> };
    assumptions: { probability: string | null; source_type: string };
  };
}

export async function loadAppData(mode: DataMode, scenario: ScenarioKind, inputs: ScenarioInputs, set: string): Promise<AppData> {
  if (!availableScenarios(set).includes(scenario)) throw new Error(`Scenario ${scenario} is unavailable in ${set}`);
  if (mode === "fixture") return loadFixtureAppData(scenario, inputs, set);

  const request = buildScenarioRequest(scenario, inputs, set);
  // Discovery activates the graph and snapshot consumed by every downstream call.
  // Wait for it before simulating, especially when live discovery takes seconds.
  const graph = await requestJson<DependencyGraph>(`${withSet("/api/v1/discover", set)}&discovery=${discoveryMode}`, post({ schema_version: "1.0" }));
  const [health, portfolio, marketSnapshot, risk, analytics] = await Promise.all([
    requestJson<{ status: string; fixture_set?: string }>(withSet("/api/v1/health", set)),
    requestJson<Portfolio>(withSet("/api/v1/portfolio", set)),
    requestJson<MarketSnapshot>(withSet("/api/v1/market-snapshot", set)),
    requestJson<RiskResult>(withSet("/api/v1/simulate", set), post(request)),
    requestJson<RiskAnalytics>(withSet("/api/v1/analyze", set), post(request)),
  ]);
  const decisionList = await Promise.all(
    portfolio.positions.map((position) =>
      requestJson<DecisionResult>(withSet("/api/v1/decide", set), post({ simulation_id: risk.simulation_id, position_id: position.position_id })),
    ),
  );
  const decisions = Object.fromEntries(decisionList.map((decision) => [decision.position_id, decision]));

  return {
    health: { status: health.status, mode: "api", source: "FastAPI · live risk engine", mockedFixtures: [], fixtureSet: health.fixture_set ?? set },
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

async function loadFixtureAppData(scenario: ScenarioKind, inputs: ScenarioInputs, set: string): Promise<AppData> {
  const surface = await loadSurface(set);
  const points = surface?.scenarios[scenario]?.points;
  if (!points?.length) throw new Error(`No computed risk surface for ${scenario} in ${set}`);

  const [live, ...others] = scenarioParams[scenario];
  const target = Number(live.value(inputs));
  const point = points.reduce((best, p) => (Math.abs(Number(p.value) - target) < Math.abs(Number(best.value) - target) ? p : best));
  const base = buildFixtureAppData(scenario, set, point.decisions);
  // Offline, only the first parameter is precomputed; say which other inputs are held at the preset.
  const preset = baseScenarioRequest(scenario, set);
  const presetParams = preset.scenario.parameters as Record<string, unknown>;
  const ignoredInputs = others
    .filter(({ param, value }) => String(presetParams[param]) !== value(inputs))
    .map(({ param }) => param);
  if (inputs.horizonDays !== preset.scenario.horizon_days) ignoredInputs.push("horizon_days");
  // At the preset values the stored result is the same run, with its calculation trace and contagion
  // paths; surface points carry neither, so use them only once the slider moves away from the preset.
  const atPreset =
    Number(point.value) === Number(presetParams[live.param]) &&
    Number(point.value) === target &&
    ignoredInputs.length === 0 &&
    !base.health.mockedFixtures.includes(fileByKind.risk(scenario));
  const risk = atPreset ? base.risk : withContagion(point.risk_result, base.risk);
  const analytics = fixtureAnalytics(scenario, inputs, set);
  return {
    ...base,
    health: { ...base.health, source: "contracts fixtures · precomputed engine surface" },
    risk,
    decision: point.decisions.aave_01 ?? Object.values(point.decisions)[0] ?? base.decision,
    decisions: point.decisions,
    analytics,
    riskSource: "surface",
    ignoredInputs,
    analyticsIsPreset: analytics !== null,
  };
}

const surfaceCache = new Map<string, Promise<RiskSurface | null>>();
function loadSurface(set: string): Promise<RiskSurface | null> {
  const loader = surfaceLoaders[`${FIXTURES}/${set}/risk_surface.json`];
  if (!loader) return Promise.resolve(null);
  if (!surfaceCache.has(set)) surfaceCache.set(set, loader().then((data) => data as RiskSurface).catch(() => null));
  return surfaceCache.get(set)!;
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

/** Offline analytics are computed at each scenario's preset (risk_analytics<suffix>.json); the depeg also has a severe preset. */
function fixtureAnalytics(scenario: ScenarioKind, inputs: ScenarioInputs, set: string): RiskAnalytics | null {
  const read = (file: string) => (smallFixtures[`${FIXTURES}/${set}/${file}`] as RiskAnalytics | undefined) ?? null;
  const preset = read(`risk_analytics${fileSuffix[scenario]}.json`);
  if (scenario !== "usde_depeg") return preset;
  const severe = read("risk_analytics_severe.json");
  return severe && inputs.shockPct >= 17.5 ? severe : preset;
}


export async function postAssistantMessage(request: AssistantRequest, mode: DataMode): Promise<AssistantResponse> {
  const draft = proposeScenario(request.message,
    kind => ({ ...request.scenarioInputs, ...presetInputs(kind, request.fixtureSet) }),
    availableScenarios(request.fixtureSet), request.graph.nodes.map(node => node.id));
  if (draft) {
    if (draft.proposal) draft.proposal.engineScenario = buildScenarioRequest(draft.proposal.scenario, draft.proposal.inputs, request.fixtureSet).scenario;
    return draft;
  }
  if (!request.data) return { message: "Describe a stress to prepare a scenario, for example: USDe falls 10%, liquidity falls 80%, over 7 days. Run a scenario before asking about losses or liquidation results.", actions: [] };
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
  // The assistant answers from the results on screen (request.data), never from stored presets.
  return parseAssistantIntent({ ...request, data: request.data! });
}

function buildFixtureAppData(scenario: ScenarioKind, set: string, decisions: Record<string, DecisionResult>): AppData {
  const mockedFixtures: string[] = [];
  const portfolio = readFixture<Portfolio>(set, "portfolio.json");
  const graph = readFixture<DependencyGraph>(set, "dependency_graph.json");
  const marketSnapshot = readFixture<MarketSnapshot>(set, "market_snapshot.json");
  const risk = readFixture<RiskResult>(set, fileByKind.risk(scenario));
  const decision = decisions.aave_01 ?? Object.values(decisions)[0];
  if (!decision) throw new Error(`No computed execution decisions for ${scenario} in ${set}`);

  return {
    health: { status: "ok", mode: "fixture", source: "contracts fixtures", mockedFixtures, fixtureSet: set },
    portfolio,
    graph,
    marketSnapshot,
    risk,
    decision,
    decisions,
    analytics: null,
    riskSource: "fixture",
    ignoredInputs: [],
    analyticsIsPreset: false,
  };
}

function readFixture<T>(set: string, fileName: string): T {
  const data = smallFixtures[`${FIXTURES}/${set}/${fileName}`];
  if (data === undefined) throw new Error(`Missing ${fileName} in ${set}; no synthetic result was substituted.`);
  return data as T;
}

function readFixtureDefault() {
  const value = import.meta.env.VITE_USE_FIXTURES;
  if (value == null || value === "") return false;
  return !["0", "false", "off", "api"].includes(String(value).toLowerCase());
}

/** Deterministic stress sweep: hold the submitted assumptions fixed and vary one factor. */
export async function compareRiskLevels(mode: DataMode, scenario: ScenarioKind, inputs: ScenarioInputs, set: string) {
  const param = scenarioParams[scenario][0].param;
  const values = scenario === 'carry_squeeze' ? [0, .2, .4, .6, .8, 1] :
    scenario === 'liquidity_crisis' ? [0, .2, .4, .6, .8, .95] :
    scenario === 'node_shock' ? [0, .1, .2, .3, .4, .5] : [0, -.1, -.2, -.3, -.4];
  if (mode === 'fixture') {
    const surface = await loadSurface(set);
    const points = surface?.scenarios[scenario]?.points;
    if (!points?.length) throw new Error('No precomputed stress comparison for this scenario.');
    return values.map(value => {
      const point = points.reduce((best, p) => Math.abs(Number(p.value) - value) < Math.abs(Number(best.value) - value) ? p : best);
      return { value: Number(point.value), risk: point.risk_result, param };
    });
  }
  return Promise.all(values.map(async value => {
    const request = buildScenarioRequest(scenario, inputs, set);
    request.scenario.parameters[param] = value.toFixed(2);
    const risk = await requestJson<RiskResult>(withSet('/api/v1/simulate', set), post(request));
    return { value, risk, param };
  }));
}
