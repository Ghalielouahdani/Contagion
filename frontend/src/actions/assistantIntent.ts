import type { AppData, DashboardAction, ScenarioInputs, ScenarioKind, View } from "../lib/types";
import { compactId, money, percent } from "../lib/format";
import { ACTION_LIMITS, validateRange } from "./registry";

export type AssistantIntentContext = {
  message: string;
  view: View;
  scenario: ScenarioKind;
  selectedPosition: string;
  inspectedExitFraction?: string | null;
  scenarioInputs: ScenarioInputs;
  data: AppData;
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
    notes.push(scenarioNames[requestedScenario]);
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
    // Scenario first: selecting a scenario loads its preset, then the requested value overrides it.
    if (!requestedScenario) actions.push({ type: "set_scenario", scenario: "liquidity_crisis" });
    actions.push({ type: "set_liquidity_loss", percent: liquidity });
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
    // New inputs: the engine recomputes on screen; quoting the previous result would contradict it.
    const changesInputs = actions.some((action) => ["set_scenario", "set_shock", "set_horizon", "set_liquidity_loss"].includes(action.type));
    return {
      actions: dedupeActions(actions),
      message: `${notes.length ? `Set ${notes.join(", ")} — ` : ""}${didRun ? "running now" : "showing it now"}. ${
        changesInputs ? "The risk engine recomputes the results on screen for these inputs." : summarizeCurrentOutcome(context)
      }`,
    };
  }

  const positionAnswer = answerPositionQuestion(context, text);
  if (positionAnswer) return positionAnswer;

  if (text.includes("recommend") || text.includes("verdict") || text.includes("stay") || text.includes("exit")) {
    return {
      actions: [{ type: "navigate_view", view: "decision" }],
      message: `The decision on screen for ${compactId(context.data.decision.position_id)} is ${context.data.decision.recommendation}. Reason: ${context.data.decision.reason}`,
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
      "I can open scenarios A to F (depeg, liquidity crisis, both combined, carry squeeze, governance change, node failure), set a shock between -1% and -40%, a horizon of 1 to 30 days, a liquidity loss of 0% to 95%, or inspect 0/25/50/75/100% exits. I only answer from the results on screen.",
  };
}

const scenarioNames: Record<ScenarioKind, string> = {
  usde_depeg: "Scenario A",
  liquidity_crisis: "Scenario B",
  combined_crisis: "Scenario C",
  carry_squeeze: "Scenario D",
  governance_change: "Scenario E",
  node_shock: "Scenario F",
};

function parseScenario(text: string): ScenarioKind | null {
  // Most specific first: "depeg and liquidity crisis" is C, not A.
  if (/\bscenario\s*c\b/.test(text) || text.includes("combined") || (text.includes("depeg") && text.includes("liquidity"))) return "combined_crisis";
  if (/\bscenario\s*d\b/.test(text) || /\b(carry|funding|squeeze|borrow rate)\b/.test(text)) return "carry_squeeze";
  if (/\bscenario\s*e\b/.test(text) || /\b(governance|oracle switch|threshold change)\b/.test(text)) return "governance_change";
  if (/\bscenario\s*f\b/.test(text) || /\b(node|custodian|exploit|hack|failure)\b/.test(text)) return "node_shock";
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
        message: `${compactId(riskiest.position_id)} has the largest conditional loss in the current result at ${money(riskiest.conditional_loss_usd)}.`,
      };
    }
    if (!selected?.risk_metric) {
      return { actions: [], message: `${compactId(context.selectedPosition)} has no health-factor or LTV metric: it is not a lending position.` };
    }
    return {
      actions: [{ type: "select_position", positionId: selected.position_id, view: "scenario" }],
      message: `${compactId(selected.position_id)} uses ${selected.risk_metric.type}. It moves from ${selected.risk_metric.before} to ${selected.risk_metric.after}; threshold is ${selected.risk_metric.threshold}, distance to liquidation ${percent(selected.risk_metric.distance_to_liquidation_after_pct)}. ${selected.risk_metric.liquidatable ? "It is liquidatable." : "It is not liquidatable."}`,
    };
  }

  return null;
}

/** Describe the result on screen (context.data), never a stored preset that may differ from it. */
function summarizeCurrentOutcome(context: AssistantIntentContext) {
  const risk = context.data.risk;
  const penalty = Number(risk.portfolio.shared_liquidity_penalty_usd ?? 0);
  return `Total conditional loss on screen is ${money(risk.portfolio.total_conditional_loss_usd)}${
    penalty > 0 ? `, including ${money(penalty)} from exits sharing the same venue` : ""
  }. Decision for ${compactId(context.data.decision.position_id)}: ${context.data.decision.recommendation}.`;
}
