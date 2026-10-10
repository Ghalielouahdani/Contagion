import type { AppData, DashboardAction, ScenarioInputs, ScenarioKind, View } from "../lib/types";
import { compactId, money, percent } from "../lib/format";
import { ACTION_LIMITS } from "./registry";

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

  // Scenario editing is handled by the proposal translator. Questions never
  // change inputs or run simulations just because they mention USDe or liquidity.
  if (/^\s*(?:run|rerun|re-run|lance|lancer)\s*(?:the|la|le)?\s*(?:scenario|simulation|simu)?\s*(?:now|maintenant)?[.!]?\s*$/.test(text)) {
    return { actions: [{ type: "run_simulation" }], message: "Running the scenario currently prepared in Scenario Lab. The engine will produce its results on screen." };
  }
  const exitFraction = parseExitFraction(text);
  if (exitFraction) {
    actions.push({ type: "set_exit_fraction", fraction: exitFraction });
    return { actions, message: `Inspecting a ${percent(exitFraction, 0)} exit. ${summarizeCurrentOutcome(context)}` };
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
      "Describe a stress to prepare one of scenarios A–G, or ask about the results on screen. Example: USDe falls 10%, liquidity falls 80%, over 7 days. Drafting a scenario does not run it.",
  };
}

function parseExitFraction(text: string) {
  const match = text.match(/\b(0|25|50|75|100)\s*(?:%|percent)?\s*(?:exit|reduce|reduction)?\b/);
  if (!match || !/\b(exit|reduce|compare)\b/.test(text)) return null;
  const fraction = (Number(match[1]) / 100).toFixed(2);
  return ACTION_LIMITS.exitFractions.has(fraction) ? fraction : null;
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
