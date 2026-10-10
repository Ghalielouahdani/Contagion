import { createServer } from 'vite';
import assert from 'node:assert/strict';
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
try {
  const { proposeScenario } = await server.ssrLoadModule('/src/actions/scenarioDraft.ts');
  const api = await server.ssrLoadModule('/src/data/api.ts');
  const set = 'stress_portfolio_01';
  const baseline = await api.loadPortfolioData('fixture', set);
  const base = { shockPct: 5, horizonDays: 7, liquidityLossPct: 80, ltShiftPct: -5, susdeApyPct: 0, borrowApyPct: 60, nodeId: 'offchain:ethena_backing', nodeLossPct: 10 };
  const parse = message => proposeScenario(message, kind => ({ ...base, ...api.presetInputs(kind, set) }), api.availableScenarios(set), baseline.graph.nodes.map(n => n.id));
  for (const [text, kind, expected] of [
    ['USDe baisse de 12,5 % sur 9 jours', 'usde_depeg', { shockPct: 12.5, horizonDays: 9 }],
    ['Teste une perte de liquidité de 70 % sur 3 jours', 'liquidity_crisis', { liquidityLossPct: 70, horizonDays: 3 }],
    ['USDe falls 10%, liquidity falls 80%, over 7 days', 'combined_crisis', { shockPct: 10, liquidityLossPct: 80 }],
    ['Crée une cascade avec USDe -8 %, liquidité -60 %, sur 7 jours', 'liquidation_cascade', { shockPct: 8, liquidityLossPct: 60 }],
    ['Rendement sUSDe -5 %, emprunt 65 % sur 30 jours', 'carry_squeeze', { susdeApyPct: -5, borrowApyPct: 65, horizonDays: 30 }],
    ['Gouvernance: baisse des seuils de 3 points, USDe -15 %', 'governance_change', { ltShiftPct: -3, shockPct: 15 }],
    ['Défaillance du backing Ethena: perte 20 % sur 7 jours', 'node_shock', { nodeId: 'offchain:ethena_backing', nodeLossPct: 20 }],
  ]) {
    const response = parse(text);
    assert.ok(response.proposal, response.message);
    assert.equal(response.proposal.scenario, kind);
    for (const [key, value] of Object.entries(expected)) assert.equal(response.proposal.inputs[key], value, text);
    assert.deepEqual(response.actions, []);
  }
  for (const text of ['USDe -60 %', 'USDe -10 % sur 2,5 jours', 'USDe -10 % sur -7 jours', 'Liquidité augmente de 80 %', 'USDe -10 %, beta 150 %', 'USDe -10 % sur 90 jours', 'USDe augmente de 10 %', 'USDe -10 %, ETH -20 %', 'USDe -10 %, USDe -20 %', 'Défaillance market:absent perte 20 %', 'USDe et liquidité baisse de 80 %']) {
    const response = parse(text);
    assert.equal(response.proposal, undefined, text);
    assert.deepEqual(response.actions, []);
  }
  assert.equal(parse('Pourquoi le depeg USDe touche mon prêteur ?'), null);
  const request = { message: 'USD INTEREST RATE FALLS BY 3 PTN', scenario: 'usde_depeg', selectedPosition: 'aave_01', scenarioInputs: base, fixtureSet: set, graph: baseline.graph };
  const originalFetch = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return new Response(JSON.stringify({ message: 'Provider response', proposals: [], actions: [] }), { status: 200 });
    };
    for (const view of ['portfolio', 'graph', 'scenario', 'engine']) {
      const response = await api.postAssistantMessage({ ...request, view, count: 2 }, 'api');
      assert.equal(response.message, 'Provider response');
      assert.ok(calls.at(-1).url.includes('/api/v1/risk/assistant?set=stress_portfolio_01'), view);
      assert.deepEqual(calls.at(-1).body, { message: request.message, count: 2 });
      await assert.rejects(api.postAssistantMessage({ ...request, view }, 'fixture'), /requires Engine API/);
    }
    assert.equal(calls.length, 4);
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Gemini unavailable' }), { status: 503 });
    await assert.rejects(api.postAssistantMessage({ ...request, view: 'scenario' }, 'api'), /Gemini unavailable/);
    const execution = await api.postAssistantMessage({ ...request, message: 'USDe -10 %, liquidité -80 %, 7 jours', view: 'decision' }, 'api');
    assert.equal(execution.proposal.engineScenario.parameters.usde_spot_shock_pct, '-0.10');
    assert.deepEqual(execution.actions, []);
    // A generated case must take precedence over the currently selected preset/sliders.
    for (const kind of ['carry_squeeze', 'liquidity_crisis', 'liquidation_cascade']) {
      const generated = api.buildScenarioRequest(kind, { ...base, horizonDays: 23 }, set);
      generated.request_id = 'saved_generated_case';
      const unchanged = structuredClone(generated);
      const runCalls = [];
      globalThis.fetch = async (url, options) => {
        const body = options?.body ? JSON.parse(options.body) : null;
        runCalls.push({ url, body });
        let value = {};
        if (url.includes('/discover')) value = baseline.graph;
        else if (url.includes('/market-snapshot')) value = baseline.marketSnapshot;
        else if (url.includes('/portfolio')) value = baseline.portfolio;
        else if (url.includes('/simulate')) value = { simulation_id: 'generated_run', scenario_id: body.scenario.scenario_id };
        else if (url.includes('/decide')) {
          assert.equal(body.simulation_id, 'generated_run');
          value = { position_id: body.position_id };
        }
        return new Response(JSON.stringify(value), { status: 200 });
      };
      const result = await api.loadAppData('api', 'usde_depeg', { ...base, horizonDays: 7, shockPct: 40 }, set, generated);
      assert.equal(result.risk.scenario_id, kind);
      for (const endpoint of ['/simulate', '/analyze']) {
        const actual = runCalls.find(call => call.url.includes(endpoint)).body;
        assert.deepEqual(actual.scenario, generated.scenario, kind + endpoint);
        assert.deepEqual(actual.assumptions, generated.assumptions);
        assert.equal(actual.portfolio_id, generated.portfolio_id);
      }
      assert.deepEqual(generated, unchanged, 'running does not mutate the saved card');
    }

  } finally { globalThis.fetch = originalFetch; }
  console.log('PASS: seven scenarios, FR/EN, distinct percentages, signed carry, decimal inputs, refused ambiguity and unsupported shocks, no automatic run, Gemini routing from all four risk views before first run, no local fallback on errors, Engine API required, Execution behavior preserved, generated requests override different presets and sliders without mutation.');
} finally { await server.close(); }
