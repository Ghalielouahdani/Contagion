import { useState, type CSSProperties } from "react";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { compactId, labelize, money, percent } from "./lib/format";
import type { AppData } from "./lib/types";

type Stage = { title: string; value: string; link: string; explanation: string };
const moves = (values: Record<string, string>) => Object.entries(values).map(([asset, value]) => `${asset} ${percent(value, 2)}`).join(" · ");

/** Explain recorded engine outputs. Intermediate portfolio metrics are never invented. */
export function RiskCausalChain({ data, onInspect }: { data: AppData; onInspect: (position: string) => void }) {
  const { risk } = data;
  const cascade = risk.cascade;
  const [stage, setStage] = useState(0);
  const [roundIndex, setRoundIndex] = useState(0);
  const round = cascade?.rounds[roundIndex];
  const previousMoves = cascade ? (roundIndex ? cascade.rounds[roundIndex - 1].moves : cascade.initial_moves) : {};
  const borrowers = risk.positions.filter(p => p.risk_metric);
  const liquidatable = borrowers.filter(p => p.risk_metric?.liquidatable);
  const reference = risk.comparison?.runs.find(run => run.run_id === "initial_shock_only");
  const names = new Map(data.graph.nodes.map(node => [node.id, node.label]));
  const stages: Stage[] = cascade ? [
    { title: "Initial shock", value: moves(cascade.initial_moves), link: "reduces collateral value",
      explanation: "The submitted depeg lowers market prices. It starts the cascade; later price moves are calculated from forced selling." },
    { title: "Oracle & threshold", value: `${liquidatable.length}/${borrowers.length} portfolio borrows liquidatable at the end`, link: "makes debt liquidatable",
      explanation: "An oracle that follows the falling price increases debt / collateral. Morpho liquidates above LLTV; Aave below health factor 1. An oracle that ignores this price move can interrupt this path." },
    { title: "Liquidations", value: money(round?.liquidated_debt_usd ?? "0"), link: "seizes collateral to sell",
      explanation: "Liquidators repay market borrowers' debt and seize collateral if profitable. This amount covers the modelled lending markets, not only this portfolio's debt." },
    { title: "Forced sales", value: money(round?.collateral_sold_usd ?? "0"), link: "consumes exit liquidity",
      explanation: "Seized collateral is sold through the collateral's exit venue. Larger orders and less available depth worsen execution prices. This selling is market-wide, not a portfolio exit instruction." },
    { title: "Price feedback", value: round ? moves(round.moves) : moves(cascade.final_moves), link: "can trigger the next round",
      explanation: "The exit curve translates selling pressure into another price move. That move is used in the next liquidation test. Arbitrage absorption can also let prices recover between rounds." },
    { title: "Portfolio impact", value: money(risk.portfolio.total_conditional_loss_usd), link: "",
      explanation: "The engine values holdings and borrows at final prices, adds liquidation penalties, and allocates lender losses from market bad debt and underwater debt. This is the final run result, not this round's loss." },
  ] : [
    { title: "Stress applied", value: `${labelize(String(risk.scenario_id))} · ${risk.horizon_days} days`, link: "changes values or market rules",
      explanation: risk.scenario_id === "carry_squeeze"
        ? "Interest accrues over the horizon: debt grows at the borrow rate while collateral follows its yield. Rising debt relative to collateral can cross a liquidation threshold without a price shock."
        : "The engine applies the submitted stress to the affected prices, dependency values, liquidity or protocol rules. The calculation trace below records the exact inputs." },
    { title: "Position effects", value: `${liquidatable.length}/${borrowers.length} borrows liquidatable`, link: "changes portfolio equity",
      explanation: "Each position is repriced through its dependencies. Borrowers are tested against their protocol's oracle and threshold; lenders are exposed through borrowers' collateral coverage. Exit costs apply when this scenario models an exit." },
    { title: "Portfolio impact", value: money(risk.portfolio.total_conditional_loss_usd), link: "",
      explanation: "Position loss components and any portfolio-only shared liquidity penalty are aggregated. Dependency paths explain exposure; multiple paths do not multiply the same loss." },
  ];

  return (
    <section className="visual-panel engine-causality" aria-label="Cause and effect">
      <p className="eyebrow">Cause → mechanism → consequence</p>
      <h2>How this stress reaches your portfolio</h2>
      <p className="microcopy">Select an event to see the mechanism and its evidence from this run.</p>
      {cascade ? (
        <div className="causal-round-controls">
          <button className="text-button" aria-label="Previous cascade round" disabled={roundIndex === 0} onClick={() => setRoundIndex(roundIndex - 1)}><ChevronLeft size={16} /></button>
          <label>Round <select aria-label="Cascade round" value={roundIndex} onChange={e => setRoundIndex(Number(e.target.value))}>
            {cascade.rounds.map((r, i) => <option key={r.round} value={i}>{r.round}{Number(r.liquidated_debt_usd) === 0 ? " · no new liquidations" : ""}</option>)}
          </select> of {cascade.rounds.length}</label>
          <button className="text-button" aria-label="Next cascade round" disabled={roundIndex === cascade.rounds.length - 1} onClick={() => setRoundIndex(roundIndex + 1)}><ChevronRight size={16} /></button>
          <span className="microcopy">Model iterations, not days · horizon {risk.horizon_days} days</span>
        </div>
      ) : <p className="microcopy">This run does not simulate liquidation feedback round by round. Run “Liquidation cascade” to follow forced sales and subsequent price moves.</p>}
      <ol className="causal-chain" style={{ "--causal-count": stages.length } as CSSProperties}>
        {stages.map((item, index) => (
          <li key={item.title}>
            <button className="causal-event" aria-pressed={stage === index} onClick={() => setStage(index)}>
              <span className="causal-number">{index + 1}</span>
              <strong>{item.title}</strong><span className="causal-value">{item.value}</span>
              <small>{index === 2 || index === 3 ? (cascade ? "Selected round · market-wide" : "Final portfolio result") : index === 5 ? "Final portfolio result" : ""}</small>
            </button>
            {item.link ? <div className="causal-link"><ArrowRight size={18} /><span>{item.link}</span></div> : null}
          </li>
        ))}
      </ol>
      <div className="causal-detail" aria-live="polite">
        <h3>{stages[stage].title}</h3>
        <p>{stages[stage].explanation}</p>
        {cascade && stage === 4 && round ? <p className="microcopy">Entering round {round.round}: {moves(previousMoves)} → after selling and absorption: {moves(round.moves)}.</p> : null}
        {(stage === 1 || (!cascade && stage === 0)) ? (
          <div className="causal-metrics">
            {borrowers.map(position => {
              const metric = position.risk_metric!;
              const isLtv = metric.type === "ltv";
              return <button key={position.position_id} className="causal-position" onClick={() => onInspect(position.position_id)}>
                <strong>{compactId(position.position_id)}</strong>
                <span>{isLtv ? "LTV" : "Health factor"}: {isLtv ? percent(metric.before, 2) : Number(metric.before).toFixed(3)} → {isLtv ? percent(metric.after, 2) : Number(metric.after).toFixed(3)}</span>
                <span>Liquidation {isLtv ? "above" : "below"} {isLtv ? percent(metric.threshold, 2) : "1"}</span>
                <small>{metric.liquidatable ? "Threshold crossed" : "Threshold not crossed"} · final run values · view calculation →</small>
              </button>;
            })}
          </div>
        ) : null}
        {(stage === stages.length - 1) ? (
          <div className="causal-metrics">
            {risk.positions.map(position => {
              const path = position.contagion?.paths[0];
              return <button key={position.position_id} className="causal-position" onClick={() => onInspect(position.position_id)}>
                <strong>{compactId(position.position_id)} · {money(position.conditional_loss_usd)}</strong>
                <span>{path ? [...path.nodes].reverse().map(node => names.get(node) ?? compactId(node)).join(" → ") : "No dependency path recorded"}</span>
                <small>Final position loss · view calculation →</small>
              </button>;
            })}
          </div>
        ) : null}
      </div>
      {cascade ? (
        <div className="causal-outcome">
          <span>Initial shock only <strong>{reference ? money(reference.total_conditional_loss_usd) : "unavailable"}</strong></span>
          <ArrowRight size={20} />
          <span>With liquidation feedback <strong>{money(risk.portfolio.total_conditional_loss_usd)}</strong></span>
          <span>Additional loss from feedback <strong>{reference && risk.comparison?.excess_loss_usd != null ? money(risk.comparison.excess_loss_usd) : "unavailable"}</strong></span>
        </div>
      ) : null}
      {cascade && !cascade.converged ? <p className="engine-warning">The cascade reached its iteration limit; the final result has not converged.</p> : null}
    </section>
  );
}
