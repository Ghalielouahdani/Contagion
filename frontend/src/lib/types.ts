export type ScenarioKind = "usde_depeg" | "liquidity_crisis";
export type View = "portfolio" | "graph" | "scenario" | "decision";
export type DataMode = "fixture" | "api";

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
  health: { status: string; mode: DataMode; source: string; mockedFixtures: string[] };
  portfolio: Portfolio;
  graph: DependencyGraph;
  marketSnapshot: MarketSnapshot;
  risk: RiskResult;
  decision: DecisionResult;
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
  scenarioInputs: {
    shockPct: number;
    horizonDays: number;
    liquidityLossPct: number;
  };
  data: AppData;
};

export type AssistantResponse = {
  message: string;
  actions?: DashboardAction[];
};
