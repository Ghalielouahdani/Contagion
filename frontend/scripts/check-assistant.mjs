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
  const response = await api.postAssistantMessage({ message: 'USDe -10 %, liquidité -80 %, 7 jours', view: 'portfolio', scenario: 'usde_depeg', selectedPosition: 'aave_01', scenarioInputs: base, fixtureSet: set, graph: baseline.graph }, 'api');
  assert.equal(response.proposal.engineScenario.parameters.usde_spot_shock_pct, '-0.10');
  assert.equal(response.proposal.engineScenario.parameters.exit_liquidity_reduction_pct, '0.80');
  assert.equal(response.proposal.engineScenario.horizon_days, 7);
  const help = await api.postAssistantMessage({ message: 'Quelle est ma perte ?', view: 'portfolio', scenario: 'usde_depeg', selectedPosition: 'aave_01', scenarioInputs: base, fixtureSet: set, graph: baseline.graph }, 'api');
  assert.ok(help.message.includes('Run a scenario'));
  console.log('PASS: seven scenarios, FR/EN, distinct percentages, signed carry, decimal inputs, refused ambiguity and unsupported shocks, no automatic run, exact engine parameters before first run.');
} finally { await server.close(); }
