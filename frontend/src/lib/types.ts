import portfolioFixture from "../../../contracts/fixtures/demo_ethena_01/portfolio.json";
import graphFixture from "../../../contracts/fixtures/demo_ethena_01/dependency_graph.json";
import riskDepegFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result.json";
import decisionFixture from "../../../contracts/fixtures/demo_ethena_01/decision_result.json";

export type ScenarioKind = "usde_depeg" | "liquidity_crisis";
export type View = "portfolio" | "graph" | "scenario" | "decision";
export type DataMode = "fixture" | "api";
export type Portfolio = typeof portfolioFixture;
export type PortfolioPosition = Portfolio["positions"][number];
export type DependencyGraph = typeof graphFixture;
export type GraphNode = DependencyGraph["nodes"][number];
export type GraphEdge = DependencyGraph["edges"][number];
export type DecisionResult = typeof decisionFixture;
export type ExitOption = DecisionResult["exit_options"][number];

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

export type RiskResult = Omit<typeof riskDepegFixture, "positions"> & {
  positions: RiskPosition[];
};

export type AppData = {
  health: { status: string; mode: DataMode };
  portfolio: Portfolio;
  graph: DependencyGraph;
  risk: RiskResult;
  decision: DecisionResult;
};

export type DashboardAction =
  | { type: "navigate_view"; view: View }
  | { type: "select_position"; positionId: string; view?: View }
  | { type: "select_scenario"; scenario: ScenarioKind; run?: boolean }
  | { type: "run_scenario"; scenario?: ScenarioKind }
  | { type: "open_graph_for_position"; positionId: string }
  | { type: "inspect_exit_fraction"; fraction: string }
  | { type: "toggle_data_mode" }
  | { type: "toggle_theme" };

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  caption?: string;
  action?: DashboardAction;
};

export type AssistantRequest = {
  message: string;
  view: View;
  scenario: ScenarioKind;
  selectedPosition: string;
  inspectedExitFraction?: string | null;
  data: AppData;
};

export type AssistantResponse = {
  message: string;
  action?: DashboardAction;
};
