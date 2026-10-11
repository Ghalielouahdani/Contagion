/**
 * Decision page: the scenario is assumed to happen. The verdict is the engine's lowest-loss plan
 * (backend/execution/crisis.py): deterministic and auditable, no probability. The AI analyst
 * (backend/execution/advisor.py) explains it and proposes alternatives; its strategies are re-priced by
 * the engine, and the page says so when the AI recommends something that loses more.
 */
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Bot, TriangleAlert } from "lucide-react";
import { loadCrisisAdvice, loadCrisisPlan, type CrisisAdvice, type CrisisPlan, type CrisisStrategy } from "./data/api";
import { compactId, labelize, lossOrGain, loseOrGain, money } from "./lib/format";
import type { AppData, DataMode, ScenarioKind } from "./lib/types";
import { Term } from "./Term";

const STRATEGY_LABEL: Record<string, string> = {
  hold_all: "Keep everything",
  exit_all: "Exit everything",
  min_loss: "Lowest loss (engine)",
  protect_liquidations: "Only avoid liquidations",
};

export function actionLabel(action: string, fraction: string | null | undefined) {
  if (action === "hold") return "Keep";
  if (action === "deleverage") return "Deleverage to safety";
  const share = fraction && fraction !== "none" ? ` ${Math.round(Number(fraction) * 100)}%` : "";
  return `${labelize(action).replace(/^\w/, (c) => c.toUpperCase())}${share}`;
}

function strategyLabel(s: CrisisStrategy) {
  return STRATEGY_LABEL[s.strategy_id] ?? labelize(s.strategy_id).replace(/^rotate into/, "Rotate into");
}

export function CrisisVerdict({ data, mode, set, scenario }: { data: AppData; mode: DataMode; set: string; scenario: ScenarioKind }) {
  const simulationId = data.risk.simulation_id;
  const plan = useQuery({
    queryKey: ["crisis-plan", mode, set, simulationId],
    queryFn: () => loadCrisisPlan(mode, set, scenario, simulationId),
  });
  const advice = useQuery({
    queryKey: ["crisis-advice", set, simulationId],
    queryFn: () => loadCrisisAdvice(set, simulationId),
    enabled: mode === "api",
    staleTime: Infinity,
    retry: false,
  });

  if (plan.isLoading) return <p className="muted">Computing the crisis plan…</p>;
  if (plan.isError) return <p className="engine-warning">Crisis plan unavailable: {(plan.error as Error).message}</p>;
  if (!plan.data) return <p className="muted">No precomputed crisis plan for this scenario offline. Switch to the live API.</p>;
  return <VerdictBody plan={plan.data} advice={advice} mode={mode} />;
}

function VerdictBody({ plan, advice, mode }: { plan: CrisisPlan; advice: ReturnType<typeof useQuery<Awaited<ReturnType<typeof loadCrisisAdvice>>>>; mode: DataMode }) {
  const early = plan.strategies.early;
  const best = early.find((s) => s.strategy_id === "min_loss") ?? early[0];
  const hold = early.find((s) => s.strategy_id === "hold_all");
  const lateBest = plan.strategies.late.find((s) => s.strategy_id === "min_loss");
  const incurred = plan.positions.reduce((sum, p) => sum + Number(p.late.already_incurred_usd), 0);
  const lateTotal = lateBest ? Number(lateBest.total_loss_usd) + incurred : null;
  const changes = Object.entries(best.choices).filter(([, c]) => c.action !== "hold");

  return (
    <div className="page-stack">
      <section className="visual-panel">
        <div className="verdict">
          <BadgeCheck size={20} />
          <div>
            <span>Verdict if this scenario happens</span>
            <strong>
              {changes.length
                ? `Act now: ${loseOrGain(best.total_loss_usd)} instead of ${loseOrGain(hold?.total_loss_usd ?? 0, true)}`
                : "Keep the portfolio as it is"}
            </strong>
          </div>
        </div>
        <p>
          The engine compared every action on every position (keep, sell 25 to 100%, deleverage to safety, withdraw) and kept the
          combination that loses the least, selling jointly where positions share an exit venue. Acting before the move saves{" "}
          <strong>{money(best.saving_vs_hold_all_usd)}</strong> versus keeping everything.
          {lateTotal !== null ? (
            <>
              {" "}Reacting only after the move: <strong>{loseOrGain(lateTotal)}</strong> in total, because the price loss is already
              incurred and only liquidation penalties can still be avoided.
            </>
          ) : null}
        </p>
        {Number(best.total_loss_usd) < 0 ? (
          <p className="microcopy">
            A negative loss is a gain: in this scenario some positions earn more than today (for example lenders paid the higher
            borrow rates), and the plan keeps them while closing the positions that pay.
          </p>
        ) : null}
        {changes.length ? (
          <ul className="verdict-actions">
            {Object.entries(best.choices).map(([pid, c]) => (
              <li key={pid} data-hold={c.action === "hold"}>
                <strong>{compactId(pid)}</strong> · {actionLabel(c.action, c.fraction)}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="table-panel">
        <div className="panel-heading"><div><p className="eyebrow">Strategies compared · act before the move</p><h2>What each plan costs if the scenario happens</h2></div></div>
        <table>
          <thead><tr><th>Strategy</th><th><Term>Total loss</Term></th><th><Term>Saving vs keeping everything</Term></th><th><Term>Shared venue penalty</Term></th></tr></thead>
          <tbody>
            {early.map((s) => (
              <tr key={s.strategy_id} data-selected={s.strategy_id === best.strategy_id}>
                <td>{strategyLabel(s)}{s.same_as ? <small className="muted"> · same as {STRATEGY_LABEL[s.same_as] ?? s.same_as}</small> : null}</td>
                <td>{lossOrGain(s.total_loss_usd)}</td>
                <td>{money(s.saving_vs_hold_all_usd)}</td>
                <td>{money(s.shared_venue_penalty_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="table-panel">
        <div className="panel-heading"><div><p className="eyebrow">Position by position</p><h2>Best action alone, early and late</h2></div></div>
        <table>
          <thead><tr><th>Position</th><th><Term>Loss if kept</Term></th><th>Best early action</th><th><Term>Total loss</Term></th><th>Best late action</th><th><Term>Already incurred if late</Term></th></tr></thead>
          <tbody>
            {plan.positions.map((p) => (
              <tr key={p.position_id}>
                <td>{compactId(p.position_id)}</td>
                <td>{lossOrGain(p.holding_loss_usd)}</td>
                <td>{actionLabel(p.early.best.action, p.early.best.fraction)}</td>
                <td>{lossOrGain(p.early.best.total_loss_usd)}</td>
                <td>{actionLabel(p.late.best.action, p.late.best.fraction)}</td>
                <td>{money(p.late.already_incurred_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="microcopy">
          Alone, a position may pick a different action than in the portfolio plan: sales on a shared venue are priced jointly there.
        </p>
      </section>

      <AiAnalyst advice={advice} mode={mode} engineBest={best} />

      <section className="visual-panel">
        <p className="eyebrow">Hedging</p>
        <p>
          Shocked in this scenario: {Object.keys(plan.hedging.shocked_assets).join(", ") || "none"}. Usable to park proceeds:{" "}
          {plan.hedging.assets.filter((a) => a.usable_as_hedge).map((a) => a.asset).join(", ") || "none priced"}.
          {plan.hedging.unpriced_instruments?.length ? <>
            {" Not priced: "}
            {plan.hedging.unpriced_instruments.map((item, index) => (
              <span key={item.instrument} title={item.why_unpriced}>
                {index > 0 ? ", " : ""}{item.instrument}
              </span>
            ))}.
          </> : null}
        </p>
        {plan.warnings.map((w) => <p key={w} className="microcopy">{w}</p>)}
      </section>
    </div>
  );
}

function AiAnalyst({ advice, mode, engineBest }: { advice: { data?: { advice: CrisisAdvice | null; advice_error: { message: string } | null }; isLoading: boolean; isError: boolean; error: unknown }; mode: DataMode; engineBest: CrisisStrategy }) {
  if (mode !== "api") return <section className="visual-panel"><p className="eyebrow">AI analyst</p><p className="muted">Available with the live API (the model runs on the backend).</p></section>;
  if (advice.isLoading) return <section className="visual-panel"><p className="eyebrow">AI analyst</p><p className="muted">The analyst is reading the engine's figures…</p></section>;
  const error = advice.isError ? (advice.error as Error).message : advice.data?.advice_error?.message;
  const ai = advice.data?.advice;
  if (error || !ai) return <section className="visual-panel"><p className="eyebrow">AI analyst</p><p className="engine-warning">Unavailable: {error ?? "no answer"}. The engine verdict above does not depend on it.</p></section>;

  const pick = ai.strategies[ai.recommended_strategy_index];
  const comparable = (s: CrisisAdvice["strategies"][number]) => Number(s.computed_result.total_including_incurred_usd ?? s.computed_result.total_loss_usd);
  const gap = comparable(pick) - Number(engineBest.total_loss_usd);
  const warnings = [...ai.consistency_warnings, ...(ai.ungrounded_numbers.length ? [`Numbers not found in the engine's data: ${ai.ungrounded_numbers.join(", ")}`] : [])];

  return (
    <section className="visual-panel">
      <div className="panel-heading">
        <div><p className="eyebrow"><Bot size={14} /> AI analyst · explains the engine, figures recomputed by the engine</p><h2>{pick.name}</h2></div>
        {gap > 1 ? <span className="engine-warning"><TriangleAlert size={14} /> Loses {money(gap)} more than the engine verdict: the verdict stands</span> : <span className="muted">Agrees with the engine verdict</span>}
      </div>
      <p>{ai.scenario_explanation}</p>
      <p><strong>Why this plan:</strong> {ai.recommendation_rationale}</p>
      <table>
        <thead><tr><th>AI strategy</th><th>When</th><th><Term>Total loss</Term></th><th>Actions</th></tr></thead>
        <tbody>
          {ai.strategies.map((s, i) => (
            <tr key={s.name} data-selected={i === ai.recommended_strategy_index}>
              <td>{s.name}{s.matches_candidate ? <small className="muted"> · same as {STRATEGY_LABEL[s.matches_candidate] ?? s.matches_candidate}</small> : null}</td>
              <td>{s.timing === "late" ? "after the move" : "before the move"}</td>
              <td>
                {lossOrGain(comparable(s))}
                {s.timing === "late" ? <small className="muted"> · incl. {money(s.computed_result.already_incurred_usd)} already lost</small> : null}
              </td>
              <td>{s.actions.map((a) => `${compactId(a.position_id)}: ${actionLabel(a.action, a.fraction)}`).join(" · ") || "keep everything"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="verdict-actions">
        {ai.position_assessments.map((p) => <li key={p.position_id}><strong>{compactId(p.position_id)}</strong> · {p.situation} {p.key_risk}</li>)}
      </ul>
      {[...ai.caveats, ...ai.hedging_notes].map((c) => <p key={c} className="microcopy">{c}</p>)}
      {warnings.map((w) => <p key={w} className="engine-warning">{w}</p>)}
    </section>
  );
}
