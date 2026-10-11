/**
 * Risk Engine page: the engine's reasoning, portfolio first, before any execution verdict.
 *
 * Read top to bottom: what was simulated -> what the portfolio loses and why (by mechanism)
 * -> which positions carry it -> every calculation step with its formula, inputs and their
 * provenance -> the family of simulations around this run (loss curves, breaking points,
 * sensitivity, reference runs, cascade) -> probabilities, only from weights the risk manager
 * enters -> hand-off to execution. Everything shown comes from /simulate (risk_result, with its
 * calculation trace) and /analyze (risk_analytics); nothing is recomputed here except the
 * probability-weighted statistics, which are explicit arithmetic on the engine's loss curve.
 */
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, ChevronDown, ChevronRight } from "lucide-react";
import { compactId, labelize, money, percent } from "./lib/format";
import { Term } from "./Term";
import type { AppData, RiskPosition } from "./lib/types";
import "./risk-engine.css";
import { AssumptionRegister, PositionSheets } from "./RiskPositions";
import { RiskCausalChain } from "./RiskCausalChain";
import { ScenarioStory } from "./ScenarioStory";
import { COMPONENT_COPY } from "./lib/lossComponents";
import { CountMoney, RevealOnView } from "./motion/primitives";

type TraceInput = { name: string; value: string | boolean | null; unit: string; source: string };
type TraceStep = {
  id: string;
  label: string;
  formula: string;
  inputs: TraceInput[];
  result: { value: string | boolean | null; unit: string };
  note?: string;
  rows?: Array<Record<string, string | boolean | null>>;
};
type Tornado = { assumption: string; low_value: string; high_value: string; loss_at_low_usd: string; loss_at_high_usd: string; swing_usd: string; base_loss_usd: string };
type Summary = { p05_usd: string; p25_usd: string; p50_usd: string; p75_usd: string; p95_usd: string; min_usd: string; max_usd: string; base_usd: string };
type Uncertainty = {
  draws: number;
  method: string;
  portfolio: Summary;
  positions: Record<string, Summary>;
  histogram: Array<{ from_usd: string; to_usd: string; draws: number }>;
  liquidatable_positions_share: Record<string, string>;
  drivers: Array<{ assumption: string; low: string; high: string; rank_correlation: string }>;
  fixed_because_verified: string[];
};
type PositionCurves = { x_param: string; x_values: string[]; positions_usd: Record<string, string[]>; total_usd: string[] };
type Grid = { x_param: string; x_values: string[]; y_param: string; y_values: string[]; loss_usd: string[][]; liquidatable_positions: number[][] };

const SOURCE_COPY: Record<string, string> = {
  verified: "verified on-chain",
  observed: "observed",
  derived: "computed by a previous step",
  assumed: "assumption",
  fictional: "fictional holding",
  user_scenario: "scenario parameter",
  protocol_rule: "protocol rule",
};
const TRUSTED = new Set(["verified", "observed"]);

const traceOf = (position: RiskPosition) => ((position as unknown as { trace?: TraceStep[] }).trace ?? []);

function display(value: string | boolean | null, unit: string) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (unit === "usd") return money(value);
  if (unit === "pct") return percent(value, 2);
  if (unit === "ratio" || unit === "price") return Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });
  if (unit === "tokens") return Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (unit === "days") return `${Number(value)} days`;
  return String(value);
}

export function RiskEngine({ data, onExecute }: { data: AppData; onExecute: () => void }) {
  const risk = data.risk;
  const analytics = data.analytics as (AppData["analytics"] & {
    sensitivity?: { tornado: Tornado[]; grid: Grid | null };
    uncertainty?: Uncertainty;
    position_curves?: PositionCurves | null;
    factor_exposure?: Array<{ factor: string; loss_usd: string; unit: string; exposure_usd: string; effective_leverage: string }>;
  }) | null;
  const portfolioTrace = ((risk as unknown as { trace?: TraceStep[] }).trace ?? []);
  const [selected, setSelected] = useState<string>("portfolio");

  const navBefore = risk.positions.reduce((sum, p) => sum + Number(p.net_equity_before_usd), 0);
  const total = risk.portfolio.total_conditional_loss_usd === null ? null : Number(risk.portfolio.total_conditional_loss_usd);
  const penalty = Number(risk.portfolio.shared_liquidity_penalty_usd ?? 0);

  // Scenario parameters exactly as the engine used them (trace inputs tagged user_scenario).
  const parameters = useMemo(() => {
    const seen = new Map<string, TraceInput>();
    for (const step of [...portfolioTrace, ...risk.positions.flatMap(traceOf)]) {
      for (const input of step.inputs) if (input.source === "user_scenario" && !seen.has(input.name)) seen.set(input.name, input);
    }
    return [...seen.values()];
  }, [risk]);

  // Provenance of every non-derived input: how much of the result rests on assumptions.
  const provenance = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const step of [...portfolioTrace, ...risk.positions.flatMap(traceOf)]) {
      for (const input of step.inputs) if (input.source !== "derived") counts[input.source] = (counts[input.source] ?? 0) + 1;
    }
    const all = Object.values(counts).reduce((a, b) => a + b, 0);
    const trusted = Object.entries(counts).filter(([s]) => TRUSTED.has(s)).reduce((a, [, n]) => a + n, 0);
    return { counts, all, trusted };
  }, [risk]);

  // Portfolio loss by mechanism: position components summed, plus the portfolio-only shared penalty.
  const mechanisms = useMemo(() => {
    const sums: Record<string, number> = {};
    for (const p of risk.positions) for (const [k, v] of Object.entries(p.loss_components)) sums[k] = (sums[k] ?? 0) + Number(v);
    if (penalty) sums.shared_liquidity_penalty = penalty;
    return Object.entries(sums).filter(([, v]) => Math.abs(v) >= 0.005).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  }, [risk, penalty]);
  const maxMechanism = Math.max(1, ...mechanisms.map(([, v]) => Math.abs(v)));

  const steps = selected === "portfolio" ? portfolioTrace : traceOf(risk.positions.find((p) => p.position_id === selected) ?? risk.positions[0]);

  return (
    <div className="engine-page">
      <section className="visual-panel engine-intro">
        <p className="eyebrow">Step 1 · What was simulated</p>
        <h2>{labelize(String(risk.scenario_id))} · {risk.horizon_days}-day horizon</h2>
        <p className="microcopy">
          A conditional stress: what happens <em>if</em> this scenario occurs. The engine never assumes how likely it is; probabilities only
          appear in step 7, from weights you enter.
        </p>
        <div className="engine-params">
          {parameters.length ? parameters.map((p) => (
            <span key={p.name} className="engine-chip">{p.name}: <strong>{display(p.value, p.unit)}</strong></span>
          )) : <span className="muted">No scenario parameter recorded in the trace.</span>}
        </div>
      </section>

      <ScenarioStory key={`story-${risk.simulation_id}`} data={data} />

      {data.riskSource === "surface" && data.analyticsIsPreset && analytics ? (
        <p className="engine-banner">
          Offline: the loss, the breakdown and the calculation trace follow your sliders. The uncertainty range, curves,
          sensitivities and probabilities come from this scenario's preset run (loss {money(analytics.headline.scenario_loss_usd)});
          switch to the live API to recompute them at your exact settings.
        </p>
      ) : null}

      <section className="impact-strip">
        <div className="stat"><span><Term>Net equity before</Term></span><strong><CountMoney value={navBefore} /></strong><small>Sum of positions, gross and debt netted</small></div>
        <div className="stat"><span><Term>Conditional loss</Term></span><strong>{total === null ? "incomplete" : <CountMoney value={total} />}</strong>
          <small>{total !== null && navBefore ? `${percent(total / navBefore, 2)} of net equity` : risk.portfolio.aggregation_status}</small></div>
        <div className="stat"><span><Term>Net equity after</Term></span><strong><CountMoney value={risk.portfolio.net_equity_after_usd === null ? null : Number(risk.portfolio.net_equity_after_usd)} /></strong><small>If the scenario occurs</small></div>
        <div className="stat"><span><Term>Inputs resting on observed data</Term></span><strong>{provenance.all ? percent(provenance.trusted / provenance.all, 0) : "n/a"}</strong>
          <small>{Object.entries(provenance.counts).map(([s, n]) => `${n} ${SOURCE_COPY[s] ?? s}`).join(" · ")}</small></div>
      </section>

      <RiskCausalChain key={risk.simulation_id} data={data} onInspect={position => {
        setSelected(position);
        document.getElementById("engine-calculation-trace")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }} />

      <UncertaintyPanel uncertainty={analytics?.uncertainty ?? null} />

      <section className="visual-panel">
        <p className="eyebrow">Step 3 · Where the portfolio loss comes from</p>
        <h2>Loss by mechanism, whole portfolio</h2>
        <p className="microcopy">Each mechanism is computed once and never double counted; the shared exit-venue penalty exists only for the portfolio.</p>
        <RevealOnView className="engine-bars" minHeight={mechanisms.length * 36}>
          {mechanisms.map(([key, value]) => (
            <div key={key} className="engine-bar-row">
              <span>{COMPONENT_COPY[key] ?? labelize(key)}</span>
              <div className="engine-bar-track"><div className="engine-bar" data-gain={value < 0} style={{ width: `${(Math.abs(value) / maxMechanism) * 100}%` }} /></div>
              <strong>{money(value)}</strong>
            </div>
          ))}
          {!mechanisms.length ? <p className="muted">No loss in this scenario.</p> : null}
        </RevealOnView>
      </section>

      <PositionSheets data={data} />

      <section className="visual-panel">
        <p className="eyebrow">Step 4 · Which positions carry it</p>
        <h2>Breakdown by position</h2>
        <table className="engine-table">
          <thead><tr><th><Term>Position</Term></th><th><Term>Loss</Term></th><th><Term>Share of loss</Term></th><th><Term>Main mechanism</Term></th><th><Term>Liquidation metric</Term></th><th><Term>Evidence</Term></th><th /></tr></thead>
          <tbody>
            {risk.positions.map((p) => {
              const loss = Number(p.conditional_loss_usd);
              const main = Object.entries(p.loss_components).sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))[0];
              return (
                <tr key={p.position_id} data-selected={selected === p.position_id} onClick={() => setSelected(p.position_id)}>
                  <td>{compactId(p.position_id)}</td>
                  <td>{money(loss)}</td>
                  <td>{total ? percent(loss / total, 0) : "n/a"}</td>
                  <td>{main && Number(main[1]) !== 0 ? COMPONENT_COPY[main[0]] ?? labelize(main[0]) : "none"}</td>
                  <td>{p.risk_metric ? `${labelize(p.risk_metric.type)} ${Number(p.risk_metric.before).toFixed(3)} → ${Number(p.risk_metric.after).toFixed(3)}${p.risk_metric.liquidatable ? " · liquidatable" : ""}` : "n/a"}</td>
                  <td>{p.contagion?.evidence_confidence ?? "n/a"}</td>
                  <td><button className="text-button" onClick={() => setSelected(p.position_id)}>Show calculation</button></td>
                </tr>
              );
            })}
            {penalty ? (
              <tr data-selected={selected === "portfolio"} onClick={() => setSelected("portfolio")}>
                <td>Portfolio only</td><td>{money(penalty)}</td><td>{total ? percent(penalty / total, 0) : "n/a"}</td>
                <td>Shared exit venues</td><td>n/a</td><td>n/a</td>
                <td><button className="text-button" onClick={() => setSelected("portfolio")}>Show calculation</button></td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>

      <section className="visual-panel">
        <p id="engine-calculation-trace" className="eyebrow">Step 5 · Every number, from its inputs</p>
        <div className="panel-heading">
          <h2>Calculation trace</h2>
          <select value={selected} onChange={(e) => setSelected(e.target.value)} aria-label="Trace of">
            <option value="portfolio">Portfolio aggregation</option>
            {risk.positions.map((p) => <option key={p.position_id} value={p.position_id}>{compactId(p.position_id)}</option>)}
          </select>
        </div>
        <p className="microcopy">Recorded while the engine computed, not rebuilt afterwards. Badges give each input's provenance.</p>
        <ol className="engine-steps">
          {steps.map((step, index) => <StepCard key={`${step.id}-${index}`} step={step} index={index + 1} />)}
          {!steps.length ? (
            <p className="muted">
              {data.riskSource === "surface"
                ? "Offline slider values come from a precomputed surface that stores results without their calculation trace. Run at the preset value, or switch to the live API, to see every step."
                : "No calculation trace in this result."}
            </p>
          ) : null}
        </ol>
      </section>

      <AssumptionRegister data={data} />

      <Simulations data={data} analytics={analytics} />

      <Probabilities grid={analytics?.sensitivity?.grid ?? null} navBefore={navBefore}
        breakEven={analytics?.headline?.targeted_plan_break_even_probability ?? null} />

      <section className="visual-panel engine-handoff">
        <div>
          <p className="eyebrow">Step 8 · From analysis to action</p>
          <h2>Execution gives the verdict: what to do, and how</h2>
          <p className="microcopy">The decision engine uses exactly these losses, the snapshot's exit liquidity and the horizon above.</p>
        </div>
        <button className="run-card" onClick={onExecute}>Go to the verdict <ArrowRight size={16} /></button>
      </section>
    </div>
  );
}

function StepCard({ step, index }: { step: TraceStep; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="engine-step">
      <div className="engine-step-head">
        <span className="engine-step-index">{index}</span>
        <div>
          <strong>{step.label}</strong>
          <code>{step.formula}</code>
        </div>
        <span className="engine-step-result">= {display(step.result.value, step.result.unit)}</span>
      </div>
      <table className="engine-inputs">
        <tbody>
          {step.inputs.map((input) => (
            <tr key={input.name}>
              <td>{input.name}</td>
              <td>{display(input.value, input.unit)}</td>
              <td><span className="engine-source" data-source={input.source}>{SOURCE_COPY[input.source] ?? input.source}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {step.note ? <p className="microcopy">{step.note}</p> : null}
      {step.rows?.length ? (
        <>
          <button className="text-button" onClick={() => setOpen(!open)}>
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {step.rows.length} detail rows
          </button>
          {open ? (
            <table className="engine-table compact">
              <thead><tr>{Object.keys(step.rows[0]).map((k) => <th key={k}>{labelize(k)}</th>)}</tr></thead>
              <tbody>{step.rows.map((row, i) => (
                <tr key={i}>{Object.entries(row).map(([k, v]) => <td key={k}>{k.endsWith("_usd") ? money(v as string) : String(v)}</td>)}</tr>
              ))}</tbody>
            </table>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

function Simulations({ data, analytics }: {
  data: AppData;
  analytics: (AppData["analytics"] & { sensitivity?: { tornado: Tornado[]; grid: Grid | null }; position_curves?: PositionCurves | null }) | null;
}) {
  const curves = analytics?.position_curves ?? null;
  const byPosition = curves
    ? curves.x_values.map((x, j) => Object.fromEntries([["x", Number(x)], ["portfolio", Number(curves.total_usd[j])],
        ...Object.entries(curves.positions_usd).map(([pid, values]) => [compactId(pid), Number(values[j])])]))
    : [];
  const risk = data.risk;
  const grid = analytics?.sensitivity?.grid ?? null;
  const tornado = (analytics?.sensitivity?.tornado ?? []).slice(0, 6);
  const maxSwing = Math.max(1, ...tornado.map((t) => Number(t.swing_usd)));
  const curve = grid
    ? grid.x_values.map((x, j) => Object.fromEntries([["x", Number(x)], ...grid.y_values.map((y, i) => [`${labelize(grid.y_param)} ${Number(y)}`, Number(grid.loss_usd[i][j])])]))
    : [];
  const palette = ["var(--np-accent-blue)", "var(--np-accent-coral)", "var(--np-accent-gold)", "var(--np-accent-lilac)", "var(--np-accent-periwinkle)"];

  return (
    <section className="visual-panel">
      <p className="eyebrow">Step 6 · The family of simulations around this run</p>
      <h2>How the loss moves when the scenario changes</h2>
      {!analytics ? <p className="muted">Analytics are not available for this scenario in offline mode: switch to the live API to see curves and sensitivities.</p> : null}

      {grid ? (
        <>
          <h3>Loss curve: {labelize(grid.x_param)} × {labelize(grid.y_param)}</h3>
          <p className="microcopy">Each point is a full engine run. Where curves fan out, the second assumption decides the outcome.</p>
          <div className="chart-frame">
            <RevealOnView minHeight={280}>
              <ResponsiveContainer width="100%" height={280}>
              <LineChart data={curve}>
                <CartesianGrid stroke="var(--np-line)" vertical={false} />
                <XAxis dataKey="x" tickFormatter={(v) => percent(v, 0)} />
                <YAxis tickFormatter={(v) => money(v)} width={80} />
                <Tooltip formatter={(v) => money(Number(v))} labelFormatter={(v) => `${labelize(grid.x_param)} ${percent(Number(v), 0)}`} />
                <Legend />
                {grid.y_values.map((y, i) => (
                  <Line key={y} dataKey={`${labelize(grid.y_param)} ${Number(y)}`} stroke={palette[i % palette.length]} dot={false} strokeWidth={2} />
                ))}
                {total(risk) !== null ? <ReferenceLine y={total(risk) as number} stroke="var(--np-soft)" strokeDasharray="4 4" label="this run" /> : null}
              </LineChart>
            </ResponsiveContainer>
            </RevealOnView>
          </div>
        </>
      ) : null}

      {curves ? (
        <>
          <h3>Loss by position along {labelize(curves.x_param)}</h3>
          <p className="microcopy">Each position's loss for every severity of this scenario (same engine, one run per point). The dashed line is the portfolio.</p>
          <div className="chart-frame">
            <RevealOnView minHeight={280}>
              <ResponsiveContainer width="100%" height={280}>
              <LineChart data={byPosition}>
                <CartesianGrid stroke="var(--np-line)" vertical={false} />
                <XAxis dataKey="x" tickFormatter={(v) => percent(v, 0)} />
                <YAxis tickFormatter={(v) => money(v)} width={80} />
                <Tooltip formatter={(v) => money(Number(v))} labelFormatter={(v) => `${labelize(curves.x_param)} ${percent(Number(v), 0)}`} />
                <Legend />
                {Object.keys(curves.positions_usd).map((pid, i) => (
                  <Line key={pid} dataKey={compactId(pid)} stroke={palette[i % palette.length]} dot={false} strokeWidth={2} />
                ))}
                <Line dataKey="portfolio" stroke="var(--np-strong)" strokeDasharray="5 4" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
            </RevealOnView>
          </div>
        </>
      ) : null}

      {analytics?.breaking_points ? (
        <>
          <h3>Breaking points: how far before it breaks</h3>
          <table className="engine-table">
            <thead><tr><th><Term>Position</Term></th><th><Term>Shock type</Term></th><th><Term>Liquidated at</Term></th></tr></thead>
            <tbody>{analytics.breaking_points.liquidation.map((b, i) => (
              <tr key={i}><td>{compactId(b.position_id)}</td><td>{labelize(b.mechanism)}</td>
                <td>{b.immune ? "immune to this shock" : b.breaks_at_shock_pct !== null ? percent(b.breaks_at_shock_pct, 1) : "n/a"}</td></tr>
            ))}</tbody>
          </table>
          <table className="engine-table">
            <thead><tr><th><Term>Net equity drawdown</Term></th><th><Term>Reached at a USDe depeg of</Term></th></tr></thead>
            <tbody>{analytics.breaking_points.nav_drawdown.map((n, i) => (
              <tr key={i}><td>{percent(n.nav_drawdown_pct, 0)}</td><td>{n.usde_depeg_pct !== null ? percent(n.usde_depeg_pct, 1) : "not reached"}</td></tr>
            ))}</tbody>
          </table>
        </>
      ) : null}

      {tornado.length ? (
        <>
          <h3>Which assumption moves the result most</h3>
          <p className="microcopy">One assumption at a time, from its low to its high value; every other input fixed.</p>
          <RevealOnView className="engine-bars" minHeight={tornado.length * 36}>
            {tornado.map((t) => (
              <div key={t.assumption} className="engine-bar-row">
                <span>{t.assumption} <small>({t.low_value} → {t.high_value})</small></span>
                <div className="engine-bar-track"><div className="engine-bar" style={{ width: `${(Number(t.swing_usd) / maxSwing) * 100}%` }} /></div>
                <strong>{money(t.loss_at_low_usd)} → {money(t.loss_at_high_usd)}</strong>
              </div>
            ))}
          </RevealOnView>
        </>
      ) : null}

      {risk.comparison ? (
        <>
          <h3>Reference runs on the same portfolio</h3>
          <table className="engine-table">
            <tbody>
              <tr><td>This scenario</td><td>{money(risk.portfolio.total_conditional_loss_usd)}</td></tr>
              {risk.comparison.runs.map((r) => <tr key={r.run_id}><td>{r.description}</td><td>{money(r.total_conditional_loss_usd)}</td></tr>)}
              <tr><td><strong>{risk.comparison.excess_meaning}</strong></td><td><strong>{money(risk.comparison.excess_loss_usd)}</strong></td></tr>
            </tbody>
          </table>
        </>
      ) : null}

      {risk.cascade ? (
        <>
          <h3>Liquidation cascade, round by round</h3>
          <p className="microcopy">
            Amplification ×{Number(risk.cascade.amplification ?? 0).toFixed(2)} · bad debt {money(risk.cascade.bad_debt_usd)} · stuck debt {money(risk.cascade.stuck_debt_usd)}
            {risk.cascade.converged ? "" : " · did not converge"}
          </p>
          <table className="engine-table">
            <thead><tr><th><Term>Round</Term></th><th><Term>Debt liquidated</Term></th><th><Term>Collateral sold</Term></th>{Object.keys(risk.cascade.initial_moves).map((a) => <th key={a}>{a} move</th>)}</tr></thead>
            <tbody>
              <tr><td>start</td><td /><td />{Object.values(risk.cascade.initial_moves).map((m, i) => <td key={i}>{percent(m, 2)}</td>)}</tr>
              {risk.cascade.rounds.map((r) => (
                <tr key={r.round}><td>{r.round}</td><td>{money(r.liquidated_debt_usd)}</td><td>{money(r.collateral_sold_usd)}</td>
                  {Object.values(r.moves).map((m, i) => <td key={i}>{percent(m, 2)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </section>
  );
}

function total(risk: AppData["risk"]): number | null {
  return risk.portfolio.total_conditional_loss_usd === null ? null : Number(risk.portfolio.total_conditional_loss_usd);
}

/**
 * Probability layer: the risk manager weights a few points of the engine's loss curve.
 * Expected loss, VaR and expected shortfall are plain arithmetic on those weights; with no
 * weight entered nothing is shown, so no probability is ever invented.
 */
function Probabilities({ grid, navBefore, breakEven }: { grid: Grid | null; navBefore: number; breakEven: string | null }) {
  const [row, setRow] = useState(0);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [confidence, setConfidence] = useState(0.95);
  if (!grid) {
    return (
      <section className="visual-panel">
        <p className="eyebrow">Step 7 · Probabilities</p>
        <h2>No loss curve to weight for this run</h2>
        <p className="muted">Probabilities need the engine's loss curve (analytics). The engine itself never assumes a probability.</p>
      </section>
    );
  }
  const points = grid.x_values.map((x, j) => ({ x: Number(x), loss: Number(grid.loss_usd[row][j]) })).filter((p) => p.x !== 0);
  const entered = points.filter((p) => (weights[p.x] ?? 0) > 0);
  const mass = entered.reduce((s, p) => s + weights[p.x] / 100, 0);
  const base = grid.x_values.findIndex((x) => Number(x) === 0);
  const noShockLoss = base >= 0 ? Number(grid.loss_usd[row][base]) : 0;
  const outcomes = [...entered.map((p) => ({ loss: p.loss, p: weights[p.x] / 100 })), { loss: noShockLoss, p: Math.max(0, 1 - mass) }]
    .sort((a, b) => b.loss - a.loss);
  const expected = outcomes.reduce((s, o) => s + o.loss * o.p, 0);
  // VaR / ES at `confidence`: walk the tail from the worst outcome until 1 - confidence of mass is covered.
  const tail = 1 - confidence;
  let covered = 0, tailLoss = 0, varLoss = outcomes[outcomes.length - 1]?.loss ?? 0;
  for (const o of outcomes) {
    const take = Math.min(o.p, tail - covered);
    if (take <= 0) break;
    tailLoss += take * o.loss;
    covered += take;
    varLoss = o.loss;
  }
  const es = covered > 0 ? tailLoss / covered : 0;

  return (
    <section className="visual-panel">
      <p className="eyebrow">Step 7 · Probabilities (your assumptions)</p>
      <h2>Weight the scenarios you believe in</h2>
      <p className="microcopy">
        Enter the probability you give to each shock size over the horizon. The engine supplies the loss at each point; expected loss,
        VaR and expected shortfall below are only as good as these weights. Leave them empty to stay with conditional stress losses.
      </p>
      <div className="engine-params">
        <label className="engine-chip">Curve: <select value={row} onChange={(e) => setRow(Number(e.target.value))}>
          {grid.y_values.map((y, i) => <option key={y} value={i}>{labelize(grid.y_param)} {Number(y)}</option>)}
        </select></label>
        <label className="engine-chip">Confidence: <select value={confidence} onChange={(e) => setConfidence(Number(e.target.value))}>
          {[0.9, 0.95, 0.99].map((c) => <option key={c} value={c}>{percent(c, 0)}</option>)}
        </select></label>
      </div>
      <table className="engine-table">
        <thead><tr><th>{labelize(grid.x_param)}</th><th><Term>Engine loss</Term></th><th><Term>Probability over the horizon (%)</Term></th></tr></thead>
        <tbody>{points.map((p) => (
          <tr key={p.x}>
            <td>{percent(p.x, 0)}</td><td>{money(p.loss)}</td>
            <td><input type="number" min="0" max="100" step="0.1" value={weights[p.x] ?? ""} placeholder="—"
              onChange={(e) => setWeights({ ...weights, [p.x]: Number(e.target.value) })} /></td>
          </tr>
        ))}</tbody>
      </table>
      {mass > 1 ? <p className="engine-warning">Probabilities add up to more than 100%.</p> : null}
      {entered.length && mass <= 1 ? (
        <div className="impact-strip">
          <div className="stat"><span><Term>Expected loss</Term></span><strong>{money(expected)}</strong><small>{navBefore ? percent(expected / navBefore, 2) : ""} of net equity · no shock {percent(1 - mass, 1)}</small></div>
          <div className="stat"><span><Term>VaR</Term> {percent(confidence, 0)}</span><strong>{money(varLoss)}</strong><small>Loss not exceeded with {percent(confidence, 0)} probability</small></div>
          <div className="stat"><span><Term>Expected shortfall</Term> {percent(confidence, 0)}</span><strong>{money(es)}</strong><small>Average loss in the worst {percent(tail, 0)}</small></div>
        </div>
      ) : <p className="muted">No probability entered: results stay conditional (what happens if, not how likely).</p>}
      {breakEven !== null ? (
        <p className="microcopy">
          From the engine: the targeted de-risking plan pays for itself if you believe this run's scenario has more than {percent(breakEven, 2)} probability.
        </p>
      ) : null}
    </section>
  );
}


const exactUsd = (value: string) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Number(value));

/** One scenario, many plausible model assumptions: the range around the single number. */
function UncertaintyPanel({ uncertainty }: { uncertainty: Uncertainty | null }) {
  if (!uncertainty) {
    return (
      <section className="visual-panel">
        <p className="eyebrow">Step 2 · How sure is this number?</p>
        <h2>Uncertainty range not available for this run</h2>
        <p className="muted">It comes with the analytics (live API for every scenario; offline only at the depeg presets).</p>
      </section>
    );
  }
  const pf = uncertainty.portfolio;
  const all = [pf, ...Object.values(uncertainty.positions)];
  const lo = Math.min(0, ...all.map((s) => Number(s.min_usd)));
  const hi = Math.max(1, ...all.map((s) => Number(s.max_usd)));
  const histogram = uncertainty.histogram.map((b) => ({ label: money((Number(b.from_usd) + Number(b.to_usd)) / 2), draws: b.draws, range: `${exactUsd(b.from_usd)} – ${exactUsd(b.to_usd)}` }));
  return (
    <section className="visual-panel">
      <p className="eyebrow">Step 2 · How sure is this number?</p>
      <h2>Portfolio stress loss: {money(pf.p05_usd)} – {money(pf.p95_usd)}</h2>
      <p className="microcopy"><strong>Loss in USD, not remaining equity.</strong> Central 90% of {uncertainty.draws} model runs (P5–P95).
        The upper value is the 95th percentile of loss, not the maximum loss.</p>
      <p className="microcopy">Reference loss with the original assumptions: <strong>{exactUsd(pf.base_usd)}</strong>.
        Source: risk engine uncertainty analysis, using the same scenario, horizon, portfolio and market snapshot as its reference run.
        Final net equity = initial net equity − portfolio loss.</p>
      <p className="microcopy">
        Same scenario parameters, re-run {uncertainty.draws} times with uncertain model inputs sampled uniformly within their declared ranges
        (oracle types not verified, liquidation thresholds, venue depths, sUSDe beta, cascade arbitrage). Verified inputs stay fixed
        {uncertainty.fixed_because_verified.length ? ` (${uncertainty.fixed_because_verified.map(compactId).join(", ")})` : ""}.
        This measures what we do not know about the model, not how likely the scenario is.
      </p>
      <div className="engine-ranges">
        <RangeRow label="Whole portfolio loss" summary={pf} lo={lo} hi={hi} strong />
        {Object.entries(uncertainty.positions).map(([pid, summary]) => <RangeRow key={pid} label={`${compactId(pid)} · position loss`} summary={summary} lo={lo} hi={hi} />)}
        <p className="microcopy">All rows show losses in USD on the same scale. Thin bar: P5–P95 · thick bar: P25–P75 · white dot: median loss (P50) · coral tick: reference loss. Expand a row for exact amounts. Portfolio percentiles come from total loss in each run; they are not sums of position percentiles.</p>
      </div>
      <div className="engine-two-col">
        <div>
          <h3>Distribution of portfolio stress loss</h3>
          <p className="microcopy">Horizontal: portfolio loss in USD. Vertical: number of model runs in each loss interval.</p>
          <div className="chart-frame">
            <RevealOnView minHeight={200}>
              <ResponsiveContainer width="100%" height={200}>
              <BarChart data={histogram}>
                <CartesianGrid stroke="var(--np-line)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                <YAxis allowDecimals={false} width={32} />
                <Tooltip labelFormatter={(_, payload) => payload[0]?.payload?.range ?? "Loss interval (USD)"} formatter={(value) => [value, "Model runs"]} />
                <Bar name="Model runs" dataKey="draws" fill="var(--np-accent-periwinkle)" />
              </BarChart>
            </ResponsiveContainer>
            </RevealOnView>
          </div>
        </div>
        <div>
          <h3>What drives the spread</h3>
          <p className="microcopy">Spearman rank correlation with portfolio loss, from −1 to +1: a relationship across sampled runs, not dollars or a scenario probability. Input ranges use each assumption’s native units.</p>
          <table className="engine-table">
            <thead><tr><th><Term>Assumption (range)</Term></th><th><Term>Link with the loss</Term></th></tr></thead>
            <tbody>{uncertainty.drivers.slice(0, 6).map((d) => (
              <tr key={d.assumption}>
                <td>{d.assumption} <small>({Number(d.low).toFixed(2)} – {Number(d.high).toFixed(2)})</small></td>
                <td>{Number(d.rank_correlation) > 0 ? "higher → more loss" : "higher → less loss"} · {Number(d.rank_correlation).toFixed(2)}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="microcopy">
            Number of positions breaching their liquidation threshold: {Object.entries(uncertainty.liquidatable_positions_share).map(([n, share]) => `${n} positions in ${percent(share, 0)} of sampled runs`).join(" · ")}.
          </p>
        </div>
      </div>
    </section>
  );
}

function RangeRow({ label, summary, lo, hi, strong = false }: { label: string; summary: Summary; lo: number; hi: number; strong?: boolean }) {
  const x = (v: string) => `${((Number(v) - lo) / (hi - lo || 1)) * 100}%`;
  return (
    <details className="engine-range-details">
    <summary className="engine-range-row" data-strong={strong}>
      <span>{label}</span>
      <div className="engine-range-track">
        <div className="engine-range-whisker" style={{ left: x(summary.p05_usd), width: `calc(${x(summary.p95_usd)} - ${x(summary.p05_usd)})` }} />
        <div className="engine-range-box" style={{ left: x(summary.p25_usd), width: `calc(${x(summary.p75_usd)} - ${x(summary.p25_usd)})` }} />
        <div className="engine-range-median" style={{ left: x(summary.p50_usd) }} />
        <div className="engine-range-base" style={{ left: x(summary.base_usd) }} />
      </div>
      <strong>{money(summary.p05_usd)} – {money(summary.p95_usd)} <small>USD loss · P5–P95 ▾</small></strong>
    </summary>
    <table className="engine-table" aria-label={`${label}: exact loss amounts`}>
      <thead><tr><th>Loss statistic · {label}</th><th>Exact loss (USD)</th></tr></thead>
      <tbody>{([
        ["Reference · original model assumptions", summary.base_usd],
        ["P5 · 5th percentile", summary.p05_usd],
        ["P25 · 25th percentile", summary.p25_usd],
        ["P50 · median", summary.p50_usd],
        ["P75 · 75th percentile", summary.p75_usd],
        ["P95 · 95th percentile", summary.p95_usd],
        ["Minimum observed across sampled runs", summary.min_usd],
        ["Maximum observed across sampled runs", summary.max_usd],
      ]).map(([name, value]) => <tr key={name}><td>{name}</td><td>{exactUsd(value)}</td></tr>)}</tbody>
    </table>
    </details>
  );
}
