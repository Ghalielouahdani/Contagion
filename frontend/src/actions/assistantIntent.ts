import type { AppData, DashboardAction, ScenarioKind, View } from "../lib/types";
import { compactId, money, percent } from "../lib/format";
import { ACTION_LIMITS, validateRange } from "./registry";

export type AssistantIntentContext = {
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
  scenarioDataByKind?: Record<ScenarioKind, AppData>;
};

export type ParsedAssistantIntent = {
  message: string;
  actions: DashboardAction[];
};

export function parseAssistantIntent(context: AssistantIntentContext): ParsedAssistantIntent {
  const text = context.message.toLowerCase();
  const actions: DashboardAction[] = [];
  const notes: string[] = [];

  const requestedScenario = parseScenario(text);
  const shock = parseSignedPercent(text, ["shock", "depeg", "usde"]);
  const horizon = parseDays(text);
  const liquidity = parseLiquidity(text);
  const exitFraction = parseExitFraction(text);

  if (requestedScenario) {
    actions.push({ type: "set_scenario", scenario: requestedScenario });
    actions.push({ type: "navigate_view", view: "scenario" });
    notes.push(requestedScenario === "usde_depeg" ? "Scenario A" : "Scenario B");
  }

  if (shock !== null) {
    const validation = validateRange("Shock", shock, ACTION_LIMITS.shockPct.min, ACTION_LIMITS.shockPct.max, ACTION_LIMITS.shockPct.unit);
    if (!validation.ok) return refuse(validation.message);
    actions.push({ type: "set_shock", shockPct: shock });
    actions.push({ type: "navigate_view", view: "scenario" });
    notes.push(`shock -${shock}%`);
  }

  if (horizon !== null) {
    const validation = validateRange("Horizon", horizon, ACTION_LIMITS.horizonDays.min, ACTION_LIMITS.horizonDays.max, ACTION_LIMITS.horizonDays.unit);
    if (!validation.ok) return refuse(validation.message);
    actions.push({ type: "set_horizon", days: horizon });
    actions.push({ type: "navigate_view", view: "scenario" });
    notes.push(`horizon ${horizon} days`);
  }

  if (liquidity !== null) {
    const validation = validateRange("Liquidity loss", liquidity, ACTION_LIMITS.liquidityLossPct.min, ACTION_LIMITS.liquidityLossPct.max, ACTION_LIMITS.liquidityLossPct.unit);
    if (!validation.ok) return refuse(validation.message);
    actions.push({ type: "set_liquidity_loss", percent: liquidity });
    actions.push({ type: "set_scenario", scenario: "liquidity_crisis" });
    actions.push({ type: "navigate_view", view: "scenario" });
    notes.push(`liquidity loss ${liquidity}%`);
  }

  if (exitFraction) {
    actions.push({ type: "set_exit_fraction", fraction: exitFraction });
    notes.push(`${percent(exitFraction, 0)} exit`);
  }

  const asksToRun = /\b(run|rerun|re-run|simulate|simulation|now)\b/.test(text);
  if (asksToRun || actions.some((action) => ["set_scenario", "set_shock", "set_horizon", "set_liquidity_loss"].includes(action.type))) {
    actions.push({ type: "run_simulation", scenario: requestedScenario ?? undefined });
  }

  if (actions.length) {
    const didRun = actions.some((action) => action.type === "run_simulation");
    return {
      actions: dedupeActions(actions),
      message: `${notes.length ? `Set ${notes.join(", ")} — ` : ""}${didRun ? "running now" : "showing it now"}. ${summarizeCurrentOutcome(context, requestedScenario ?? context.scenario)}`,
    };
  }

  const positionAnswer = answerPositionQuestion(context, text);
  if (positionAnswer) return positionAnswer;

  if (text.includes("recommend") || text.includes("verdict") || text.includes("stay") || text.includes("exit")) {
    return {
      actions: [{ type: "navigate_view", view: "decision" }],
      message: `The decision fixture says ${context.data.decision.recommendation}. Reason: ${context.data.decision.reason}`,
    };
  }

  if (text.includes("portfolio")) {
    return {
      actions: [{ type: "navigate_view", view: "portfolio" }],
      message: `Portfolio totals: gross exposure ${money(context.data.portfolio.totals.gross_value_usd)}, debt ${money(context.data.portfolio.totals.debt_value_usd)}, net equity ${money(context.data.portfolio.totals.net_equity_usd)}.`,
    };
  }

  return {
    actions: [],
    message:
      "I can set Scenario A or B, shock between -1% and -25%, horizon 1 to 30 days, liquidity loss 0% to 95%, or inspect 0/25/50/75/100% exits. I only answer from fixture data on screen.",
  };
}

function parseScenario(text: string): ScenarioKind | null {
  if (/\bscenario\s*a\b/.test(text) || text.includes("depeg") || text.includes("usde")) return "usde_depeg";
  if (/\bscenario\s*b\b/.test(text) || text.includes("liquidity crisis") || text.includes("exit liquidity")) return "liquidity_crisis";
  return null;
}

function parseSignedPercent(text: string, anchors: string[]) {
  const hasAnchor = anchors.some((anchor) => text.includes(anchor));
  if (!hasAnchor && !/\bbump\b/.test(text)) return null;
  const match = text.match(/-?\s*(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)/);
  return match ? Math.abs(Number(match[1])) : null;
}

function parseDays(text: string) {
  const match = text.match(/(\d{1,3})\s*(?:day|days|d)\b/);
  return match ? Number(match[1]) : null;
}

function parseLiquidity(text: string) {
  if (!text.includes("liquidity")) return null;
  const match = text.match(/(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)/);
  return match ? Number(match[1]) : null;
}

function parseExitFraction(text: string) {
  const match = text.match(/\b(0|25|50|75|100)\s*(?:%|percent)?\s*(?:exit|reduce|reduction)?\b/);
  if (!match || !/\b(exit|reduce|compare)\b/.test(text)) return null;
  const fraction = (Number(match[1]) / 100).toFixed(2);
  return ACTION_LIMITS.exitFractions.has(fraction) ? fraction : null;
}

function refuse(message: string): ParsedAssistantIntent {
  return { actions: [], message };
}

function dedupeActions(actions: DashboardAction[]) {
  const result: DashboardAction[] = [];
  for (const action of actions) {
    const key = JSON.stringify(action);
    if (!result.some((item) => JSON.stringify(item) === key)) result.push(action);
  }
  return result;
}

function answerPositionQuestion(context: AssistantIntentContext, text: string): ParsedAssistantIntent | null {
  const matchedPosition = context.data.portfolio.positions.find((position) => text.includes(position.protocol) || text.includes(position.position_id.replace(/_/g, " ")));
  if (matchedPosition && (text.includes("show") || text.includes("open") || text.includes("inspect"))) {
    return {
      actions: [{ type: "select_position", positionId: matchedPosition.position_id, view: text.includes("graph") ? "graph" : "decision" }],
      message: `Opening ${matchedPosition.protocol}. Gross exposure is ${money(matchedPosition.gross_value_usd)}, debt is ${money(matchedPosition.debt_value_usd)}, and net equity is ${money(matchedPosition.net_equity_usd)}.`,
    };
  }

  if (text.includes("health factor") || text.includes("ltv") || text.includes("liquidation") || text.includes("most at risk")) {
    const ranked = [...context.data.risk.positions].sort((a, b) => Number(b.conditional_loss_usd) - Number(a.conditional_loss_usd));
    const riskiest = ranked[0];
    const selected = context.data.risk.positions.find((position) => position.position_id === context.selectedPosition);
    if (text.includes("most at risk") && riskiest) {
      return {
        actions: [{ type: "select_position", positionId: riskiest.position_id, view: "decision" }],
        message: `${compactId(riskiest.position_id)} has the largest conditional loss in the current fixture at ${money(riskiest.conditional_loss_usd)}.`,
      };
    }
    if (!selected?.risk_metric) {
      return { actions: [], message: `${compactId(context.selectedPosition)} has no health-factor or LTV metric in this fixture.` };
    }
    return {
      actions: [{ type: "select_position", positionId: selected.position_id, view: "scenario" }],
      message: `${compactId(selected.position_id)} uses ${selected.risk_metric.type}. It moves from ${selected.risk_metric.before} to ${selected.risk_metric.after}; threshold is ${selected.risk_metric.threshold}. The fixture marks liquidatable as ${selected.risk_metric.liquidatable ? "true" : "false"}.`,
    };
  }

  return null;
}

function summarizeCurrentOutcome(context: AssistantIntentContext, scenario: ScenarioKind) {
  const scenarioData = context.scenarioDataByKind?.[scenario] ?? context.data;
  if (scenario === "liquidity_crisis") {
    return `Current liquidity fixture total conditional loss is ${money(scenarioData.risk.portfolio.total_conditional_loss_usd)}, with shared liquidity penalty ${money(scenarioData.risk.portfolio.shared_liquidity_penalty_usd)}.`;
  }
  return `Current depeg fixture total conditional loss is ${money(scenarioData.risk.portfolio.total_conditional_loss_usd)}. Decision status is ${scenarioData.decision.recommendation}.`;
}
