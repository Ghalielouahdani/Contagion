import portfolioFixture from "../../../contracts/fixtures/demo_ethena_01/portfolio.json";
import graphFixture from "../../../contracts/fixtures/demo_ethena_01/dependency_graph.json";
import riskDepegFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result.json";
import riskLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/risk_result_liquidity.json";
import decisionFixture from "../../../contracts/fixtures/demo_ethena_01/decision_result.json";
import marketSnapshotFixture from "../../../contracts/fixtures/demo_ethena_01/market_snapshot.json";
import scenarioDepegFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request.json";
import scenarioLiquidityFixture from "../../../contracts/fixtures/demo_ethena_01/scenario_request_liquidity.json";
import type { AppData, DataMode, RiskResult, ScenarioKind } from "../lib/types";

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
