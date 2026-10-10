import { compactId } from "../lib/format";
import type { AppData, DashboardAction } from "../lib/types";

export const ACTION_LIMITS = {
  shockPct: { min: 1, max: 25, unit: "%" },
  horizonDays: { min: 1, max: 30, unit: " days" },
  liquidityLossPct: { min: 0, max: 95, unit: "%" },
  exitFractions: new Set(["0.00", "0.25", "0.50", "0.75", "1.00"]),
};

export const ACTION_SCHEMA = [
  "navigate_view",
  "select_position",
  "set_scenario",
  "set_shock",
  "set_horizon",
  "set_liquidity_loss",
  "run_simulation",
  "open_graph_for_position",
  "set_exit_fraction",
  "toggle_data_mode",
  "toggle_theme",
] as const;

export type ActionRegistryItem = {
  type: string;
  label: string;
  actions: DashboardAction[];
};

export function createActionRegistry(data?: AppData): ActionRegistryItem[] {
  return [
    { type: "page", label: "Portfolio Dashboard", actions: [{ type: "navigate_view", view: "portfolio" }] },
    { type: "page", label: "Dependency Graph", actions: [{ type: "navigate_view", view: "graph" }] },
    { type: "page", label: "Scenario Lab", actions: [{ type: "navigate_view", view: "scenario" }] },
    { type: "page", label: "Decision Engine", actions: [{ type: "navigate_view", view: "decision" }] },
    { type: "scenario", label: "Run Scenario A - USDe depeg", actions: [{ type: "run_simulation", scenario: "usde_depeg" }] },
    { type: "scenario", label: "Run Scenario B - liquidity crisis", actions: [{ type: "run_simulation", scenario: "liquidity_crisis" }] },
    { type: "scenario", label: "Set shock to -8%", actions: [{ type: "set_shock", shockPct: 8 }] },
    { type: "scenario", label: "Set horizon to 7 days", actions: [{ type: "set_horizon", days: 7 }] },
    { type: "scenario", label: "Set liquidity loss to 80%", actions: [{ type: "set_liquidity_loss", percent: 80 }] },
    { type: "decision", label: "Inspect 50% exit", actions: [{ type: "set_exit_fraction", fraction: "0.50" }] },
    ...(data?.portfolio.positions.map((position) => ({
      type: "position",
      label: `${position.protocol} - ${compactId(position.position_id)}`,
      actions: [{ type: "select_position", positionId: position.position_id, view: "decision" }] satisfies DashboardAction[],
    })) ?? []),
  ];
}

export function validateRange(label: string, value: number, min: number, max: number, unit: string) {
  if (value < min || value > max) {
    return { ok: false, message: `${label} must be between ${min}${unit} and ${max}${unit}. I did not change the scenario.` };
  }
  return { ok: true, message: "" };
}
