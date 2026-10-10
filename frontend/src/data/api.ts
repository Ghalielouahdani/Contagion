import portfolioFixture from "../../../contracts/fixtures/demo_ethena_01/portfolio.json";
import graphFixture from "../../../contracts/fixtures/demo_ethena_01/dependency_graph.json";
import riskDepegFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result.json";
import riskLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result_liquidity.json";
import decisionFixture from "../../../contracts/fixtures/demo_ethena_01/decision_result.json";
import marketSnapshotFixture from "../../../contracts/fixtures/demo_ethena_01/market_snapshot.json";
import scenarioDepegFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request.json";
import scenarioLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request_liquidity.json";
import { compactId, money, percent } from "../lib/format";
import type { AppData, AssistantRequest, AssistantResponse, DataMode, RiskResult, ScenarioKind } from "../lib/types";

const riskByScenario: Record<ScenarioKind, RiskResult> = {
  usde_depeg: riskDepegFixture as RiskResult,
  liquidity_crisis: riskLiquidityFixture as RiskResult,
};

const scenarioByKind = {
  usde_depeg: scenarioDepegFixture,
  liquidity_crisis: scenarioLiquidityFixture,
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
  if (mode === "fixture") {
    return {
      health: { status: "ok", mode },
      portfolio: portfolioFixture,
      graph: graphFixture,
      risk: riskByScenario[scenario],
      decision: decisionFixture,
    };
  }

  const health = await requestJson<{ status: string; mode: DataMode }>("/api/v1/health");
  const portfolio = await requestJson<typeof portfolioFixture>("/api/v1/portfolio");
  const graph = await requestJson<typeof graphFixture>("/api/v1/discover", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0", portfolio_id: portfolio.portfolio_id }),
  });
  const scenarioRequest = scenarioByKind[scenario];
  const risk = await requestJson<RiskResult>("/api/v1/simulate", {
    method: "POST",
    body: JSON.stringify(scenarioRequest),
  });
  const decision = await requestJson<typeof decisionFixture>("/api/v1/decide", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.0",
      portfolio_id: portfolio.portfolio_id,
      simulation_id: risk.simulation_id,
      position_id: "aave_01",
    }),
  });
  return { health, portfolio, graph, risk, decision };
}

export const marketSnapshot = marketSnapshotFixture;
export const scenarioFixtures = scenarioByKind;

export async function postAssistantMessage(request: AssistantRequest, mode: DataMode): Promise<AssistantResponse> {
  if (mode === "api") {
    // TODO: wire to the FastAPI backend once P4 exposes POST /api/v1/assistant.
    return requestJson<AssistantResponse>("/api/v1/assistant", {
      method: "POST",
      body: JSON.stringify({
        message: request.message,
        view: request.view,
        scenario: request.scenario,
        selected_position: request.selectedPosition,
        inspected_exit_fraction: request.inspectedExitFraction,
      }),
    });
  }

  return fixtureAssistantResponse(request);
}

function fixtureAssistantResponse(request: AssistantRequest): AssistantResponse {
  const text = request.message.toLowerCase();
  const positions = request.data.portfolio.positions;
  const matchedPosition = positions.find((position) => text.includes(position.protocol) || text.includes(position.position_id.replace(/_/g, " ")));

  if (text.includes("aave") && (text.includes("graph") || text.includes("dependency") || text.includes("depend"))) {
    return {
      message:
        "Opening the Aave dependency graph. The fixture path includes position:aave_01 -> market:aave_01 -> oracle:aave_01_usde, with assumed evidence that still needs P1 verification.",
      action: { type: "open_graph_for_position", positionId: "aave_01" },
    };
  }

  if (matchedPosition && (text.includes("show") || text.includes("open") || text.includes("inspect"))) {
    return {
      message: `Opening ${matchedPosition.protocol}. Gross exposure is ${money(matchedPosition.gross_value_usd)}, debt is ${money(matchedPosition.debt_value_usd)}, and net equity is ${money(matchedPosition.net_equity_usd)}.`,
      action: { type: "select_position", positionId: matchedPosition.position_id, view: "decision" },
    };
  }

  if (text.includes("scenario a") || text.includes("depeg") || text.includes("-5")) {
    return {
      message: "Switching to Scenario A, the USDe depeg fixture. The current golden result shows total conditional loss of " + money(request.data.risk.portfolio.total_conditional_loss_usd) + ".",
      action: { type: "run_scenario", scenario: "usde_depeg" },
    };
  }

  if (text.includes("scenario b") || text.includes("liquidity")) {
    return {
      message: "Switching to Scenario B, the liquidity crisis fixture. This separates mark value from executable exit value and flags shared venue pressure.",
      action: { type: "run_scenario", scenario: "liquidity_crisis" },
    };
  }

  const exitFraction = ["0.25", "0.50", "0.75", "1.00"].find((fraction) => {
    const pct = `${Number(fraction) * 100}%`;
    return text.includes(fraction) || text.includes(pct) || text.includes(pct.replace("%", " percent"));
  });
  if (exitFraction || text.includes("50")) {
    const fraction = exitFraction ?? "0.50";
    const option = request.data.decision.exit_options.find((item) => item.exit_fraction === fraction);
    return {
      message: option
        ? `${percent(option.exit_fraction, 0)} exit costs ${money(option.estimated_exit_cost_usd)} and leaves ${money(option.residual_stress_loss_usd)} residual stress loss. Break-even probability is ${option.break_even_probability ? percent(option.break_even_probability, 2) : "not defined for staying"}.`
        : "I can inspect 0%, 25%, 50%, 75% or 100% exits from the fixture table.",
      action: { type: "inspect_exit_fraction", fraction },
    };
  }

  if (text.includes("health factor") || text.includes("ltv") || text.includes("liquidation")) {
    const position = request.data.risk.positions.find((item) => item.position_id === request.selectedPosition);
    if (!position?.risk_metric) {
      return { message: `${compactId(request.selectedPosition)} has no lending liquidation metric in the current fixture. Token and PT holdings do not expose HF/LTV here.` };
    }
    return {
      message: `${compactId(position.position_id)} uses ${position.risk_metric.type}. It moves from ${position.risk_metric.before} to ${position.risk_metric.after}, threshold ${position.risk_metric.threshold}. Liquidatable is ${position.risk_metric.liquidatable ? "true" : "false"}.`,
      action: { type: "select_position", positionId: position.position_id, view: "scenario" },
    };
  }

  if (text.includes("recommend") || text.includes("insufficient") || text.includes("stay") || text.includes("reduce") || text.includes("exit")) {
    return {
      message: `The decision fixture says ${request.data.decision.recommendation}. Reason: ${request.data.decision.reason}`,
      action: { type: "navigate_view", view: "decision" },
    };
  }

  if (text.includes("portfolio")) {
    return {
      message: `Opening the portfolio. Total gross exposure is ${money(request.data.portfolio.totals.gross_value_usd)}, debt is ${money(request.data.portfolio.totals.debt_value_usd)}, and net equity is ${money(request.data.portfolio.totals.net_equity_usd)}.`,
      action: { type: "navigate_view", view: "portfolio" },
    };
  }

  return {
    message:
      "I can answer from the current fixtures only: portfolio exposure, dependency evidence, health factor or LTV, scenario losses, exit costs, break-even probability and warnings. I will not invent missing market data.",
  };
}
