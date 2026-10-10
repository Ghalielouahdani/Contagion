export type ScenarioKind =
  | "usde_depeg"
  | "liquidity_crisis"
  | "combined_crisis"
  | "governance_change"
  | "carry_squeeze"
  | "node_shock"
  | "liquidation_cascade";
export type View = "portfolio" | "graph" | "scenario" | "engine" | "decision";
export type DataMode = "fixture" | "api";

export type ScenarioInputs = {
  shockPct: number;
  horizonDays: number;
  liquidityLossPct: number;
  /** governance_change: signed shift of liquidation thresholds, in points (e.g. -5). */
  ltShiftPct: number;
  /** carry_squeeze: sUSDe staking APY and borrow APY over the horizon, in percent. */
  susdeApyPct: number;
  borrowApyPct: number;
  /** node_shock: graph node hit and the share of value lost there, in percent. */
  nodeId: string;
  nodeLossPct: number;
};

export type PortfolioPosition = {
  position_id: string;
  protocol: string;
  chain_id: number;
  position_type: string;
  market_id: string | null;
  asset_symbol?: string;
  collateral_asset?: string;
  debt_asset?: string;
  quantity?: string;
  gross_value_usd: string;
  debt_value_usd: string;
  net_equity_usd: string;
  exit_venue_id: string;
  data_origin: string;
  [key: string]: unknown;
};

export type Portfolio = {
  schema_version: string;
  portfolio_id: string;
  as_of: string;
  quote_currency: string;
  positions: PortfolioPosition[];
  totals: {
    gross_value_usd: string;
    debt_value_usd: string;
    net_equity_usd: string;
  };
  [key: string]: unknown;
};

export type GraphNode = {
  id: string;
  type: string;
  label: string;
  [key: string]: unknown;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  risk_channel: string;
  confidence: string;
  evidence: {
    method: string;
    reference: string;
    observed_at: string;
    status?: string;
  };
  [key: string]: unknown;
};

export type DependencyGraph = {
  schema_version: string;
  graph_id: string;
  portfolio_id: string;
  as_of: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  warnings?: string[];
  [key: string]: unknown;
};

export type RiskMetric = {
  type: string;
  before: string;
  after: string;
  threshold: string;
  liquidatable: boolean;
  distance_to_liquidation_before_pct: string;
  distance_to_liquidation_after_pct: string;
};

export type ContagionPath = {
  factor: string;
  root: string;
  nodes: string[];
  edges: string[];
  channels: string[];
  confidence: string;
  unverified_edges: string[];
};

export type PositionContagion = {
  paths: ContagionPath[];
  evidence_confidence: string | null;
  graph_gaps: string[];
  unmodeled_exposures: string[];
};

export type ContagionHub = {
  node: string;
  label: string;
  node_type: string;
  positions: string[];
  gross_exposure_usd: string;
  net_equity_usd: string;
};

export type RiskPosition = {
  position_id: string;
  gross_value_before_usd: string;
  gross_value_after_usd: string;
  executable_value_after_usd: string | null;
  debt_after_usd: string;
  net_equity_before_usd: string;
  net_equity_after_usd: string;
  conditional_loss_usd: string;
  loss_components: Record<string, string>;
  risk_metric: RiskMetric | null;
  source_type: string;
  calculation_status: string;
  warnings: string[];
  contagion?: PositionContagion;
};

export type RiskResult = {
  schema_version: string;
  simulation_id: string;
  request_id: string;
  portfolio_id: string;
  scenario_id: ScenarioKind | string;
  horizon_days: number;
  currency: string;
  positions: RiskPosition[];
  portfolio: {
    total_conditional_loss_usd: string;
    shared_liquidity_penalty_usd?: string;
    aggregation_status: string;
    [key: string]: unknown;
  };
  metadata?: Record<string, unknown>;
  warnings?: string[];
  contagion?: { graph_id: string | null; hubs: ContagionHub[]; warnings: string[] };
  /** Scenario G: liquidation rounds until prices stop moving (moves are signed fractions per asset). */
  cascade?: {
    initial_moves: Record<string, string>;
    final_moves: Record<string, string>;
    trough_moves: Record<string, string>;
    amplification: string | null;
    rounds: Array<{ round: number; liquidated_debt_usd: string; collateral_sold_usd: string; moves: Record<string, string> }>;
    liquidated_debt_usd: string;
    bad_debt_usd: string;
    stuck_debt_usd: string;
    converged: boolean;
  };
  /** Scenarios C-F: reference runs and what this scenario adds on top of them. */
  comparison?: {
    runs: Array<{ run_id: string; description: string; total_conditional_loss_usd: string }>;
    excess_loss_usd: string | null;
    excess_meaning: string;
  };
  [key: string]: unknown;
};

/** Dollar value of the engine for the fund (contracts/schemas/v1/risk_analytics.schema.json). */
export type RiskAnalytics = {
  analytics_id: string;
  scenario_id: string;
  headline: {
    nav_usd: string;
    scenario_loss_usd: string;
    scenario_loss_pct_nav: string;
    usde_exposure_usd: string;
    usde_effective_leverage: string;
    derisking_savings_usd: string;
    derisking_savings_bps_nav: string;
    liquidation_protection_net_benefit_usd: string;
    targeted_plan_break_even_probability: string | null;
    top_risk_driver: string | null;
  };
  breaking_points: {
    liquidation: Array<{ position_id: string; mechanism: string; breaks_at_shock_pct: string | null; immune: boolean }>;
    nav_drawdown: Array<{ nav_drawdown_pct: string; usde_depeg_pct: string | null; usde_price: string | null }>;
  };
  [key: string]: unknown;
};

export type ExitOption = {
  exit_fraction: string;
  fees_usd: string;
  gas_usd: string;
  price_impact_usd: string;
  estimated_exit_cost_usd: string;
  foregone_yield_usd: string;
  residual_stress_loss_usd: string;
  break_even_probability: string | null;
  objective_usd: string | null;
  quote_status: string;
};

export type DecisionResult = {
  schema_version: string;
  decision_id: string;
  simulation_id: string;
  portfolio_id: string;
  position_id: string;
  scenario_id: ScenarioKind | string;
  horizon_days: number;
  mode: string;
  currency: string;
  exit_options: ExitOption[];
  recommendation: string;
  recommended_exit_fraction: string | null;
  reason: string;
  warnings: string[];
  [key: string]: unknown;
};

export type MarketSnapshot = {
  schema_version: string;
  snapshot_id: string;
  as_of: string;
  chain_id: number;
  prices_usd: Record<string, unknown>;
  exchange_rates: Record<string, unknown>;
  markets: Record<string, unknown>;
  yields: Record<string, unknown>;
  exit_venues: Record<string, unknown>;
  warnings: string[];
  [key: string]: unknown;
};

export type AppData = {
  health: { status: string; mode: DataMode; source: string; mockedFixtures: string[]; fixtureSet: string };
  portfolio: Portfolio;
  graph: DependencyGraph;
  marketSnapshot: MarketSnapshot;
  risk: RiskResult;
  /** Decision for the default position (aave_01); per-position decisions live in `decisions`. */
  decision: DecisionResult;
  decisions: Record<string, DecisionResult>;
  /** Null when no analytics is available for this scenario and data mode. */
  analytics: RiskAnalytics | null;
  /** How the risk numbers were produced: live engine, precomputed surface, or static fixture. */
  riskSource: "engine" | "surface" | "fixture";
  /** Offline only: scenario parameters the precomputed surface could not apply (kept at the preset value). */
  ignoredInputs: string[];
  /** True when analytics come from a preset fixture rather than the current inputs. */
  analyticsIsPreset: boolean;
};

export type DashboardAction =
  | { type: "navigate_view"; view: View }
  | { type: "select_position"; positionId: string; view?: View }
  | { type: "set_scenario"; scenario: ScenarioKind }
  | { type: "set_shock"; shockPct: number }
  | { type: "set_horizon"; days: number }
  | { type: "set_liquidity_loss"; percent: number }
  | { type: "run_simulation"; scenario?: ScenarioKind }
  | { type: "open_graph_for_position"; positionId: string }
  | { type: "set_exit_fraction"; fraction: string }
  | { type: "toggle_data_mode" }
  | { type: "toggle_theme" };

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  inputMode?: "text" | "voice";
  caption?: string;
  action?: DashboardAction;
};

export type AssistantRequest = {
  message: string;
  view: View;
  scenario: ScenarioKind;
  selectedPosition: string;
  inspectedExitFraction?: string | null;
  scenarioInputs: ScenarioInputs;
  data: AppData;
};

export type AssistantResponse = {
  message: string;
  actions?: DashboardAction[];
};
