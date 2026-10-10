import { createServer } from 'vite';
import assert from 'node:assert/strict';

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
try {
  const api = await server.ssrLoadModule('/src/data/api.ts');
  for (const set of api.fixtureSets) {
    const scenarios = api.availableScenarios(set.id);
    assert.ok(scenarios.length, set.id);
    for (const scenario of scenarios) {
      const inputs = { shockPct: 5, horizonDays: 7, liquidityLossPct: 80, ltShiftPct: -5,
        susdeApyPct: 0, borrowApyPct: 60, nodeId: 'offchain:ethena_backing', nodeLossPct: 10,
        ...api.presetInputs(scenario, set.id) };
      const data = await api.loadAppData('fixture', scenario, inputs, set.id);
      assert.equal(data.health.fixtureSet, set.id);
      assert.deepEqual(data.health.mockedFixtures, []);
      assert.equal(data.riskSource, 'surface');
      assert.equal(data.risk.portfolio_id, data.portfolio.portfolio_id);
      assert.equal(data.risk.provenance.input_snapshot_id, data.marketSnapshot.snapshot_id);
      assert.equal(data.risk.scenario_id, scenario);
      assert.deepEqual(Object.keys(data.decisions).sort(), data.portfolio.positions.map(p => p.position_id).sort());
      assert.equal(data.decision.portfolio_id, data.portfolio.portfolio_id);
      const nodes = new Set(data.graph.nodes.map(node => node.id));
      const edges = new Map(data.graph.edges.map(edge => [edge.id, edge]));
      for (const position of data.risk.positions) {
        for (const path of position.contagion?.paths ?? []) {
          assert.equal(path.nodes[0], `position:${position.position_id}`);
          assert.equal(path.nodes.at(-1), path.root);
          assert.equal(path.edges.length, path.nodes.length - 1);
          assert.ok(path.nodes.every(node => nodes.has(node)));
          path.edges.forEach((id, index) => {
            const edge = edges.get(id);
            assert.ok(edge, `${set.id}: missing contagion edge ${id}`);
            assert.equal(edge.source, path.nodes[index]);
            assert.equal(edge.target, path.nodes[index + 1]);
          });
        }
      }
    }
    console.log(`${set.id}: ${scenarios.length} presets checked`);
  }
  assert.deepEqual(api.availableScenarios('live_ethena_01'), ['usde_depeg', 'liquidity_crisis']);
  await assert.rejects(() => api.loadAppData('fixture', 'carry_squeeze', {}, 'live_ethena_01'));
} finally {
  await server.close();
}
