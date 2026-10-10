import portfolioFixture from "../../../contracts/fixtures/demo_ethena_01/portfolio.json";
import graphFixture from "../../../contracts/fixtures/demo_ethena_01/dependency_graph.json";
import riskDepegFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result.json";
import riskLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result_liquidity.json";
import decisionFixture from "../../../contracts/fixtures/demo_ethena_01/decision_result.json";
import marketSnapshotFixture from "../../../contracts/fixtures/demo_ethena_01/market_snapshot.json";
import scenarioDepegFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request.json";
import scenarioLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request_liquidity.json";
import { parseAssistantIntent } from "../actions/assistantIntent";
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
    return buildFixtureAppData(scenario);
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
        scenario_inputs: request.scenarioInputs,
      }),
    });
  }

  return fixtureAssistantResponse(request);
}

function fixtureAssistantResponse(request: AssistantRequest): AssistantResponse {
  return parseAssistantIntent({
    ...request,
    scenarioDataByKind: {
      usde_depeg: buildFixtureAppData("usde_depeg"),
      liquidity_crisis: buildFixtureAppData("liquidity_crisis"),
    },
  });
}

function buildFixtureAppData(scenario: ScenarioKind): AppData {
  return {
    health: { status: "ok", mode: "fixture" },
    portfolio: portfolioFixture,
    graph: graphFixture,
    risk: riskByScenario[scenario],
    decision: decisionFixture,
  };
}
