import { useEffect, useId, useRef, useState } from "react";
import { compactId, labelize } from "./lib/format";
import type { RiskAgentBatch, RiskScenarioProposal } from "./lib/types";

export function GeneratedScenarioCard({ batch, proposal, onRun, canRun }: {
  batch: RiskAgentBatch; proposal: RiskScenarioProposal; onRun: (proposal: RiskScenarioProposal) => void; canRun: boolean;
}) {
  const [open, setOpen] = useState(false);
  const detailsButton = useRef<HTMLButtonElement>(null);
  return <>
    <article className="preset-card generated-scenario-card">
      <span>Generated · {labelize(proposal.request.scenario.scenario_id)}</span>
      <strong>{proposal.title}</strong>
      <p>{proposal.causalChain[0] || "Portfolio-specific stress hypothesis"}</p>
      <small>{proposal.request.scenario.horizon_days} days · {proposal.affectedPositions.length} positions · not a computed loss</small>
      <div className="generated-scenario-actions">
        <button ref={detailsButton} onClick={() => setOpen(true)}>Details</button>
        <button disabled={!canRun} onClick={() => onRun(proposal)}>Run this stress case</button>
      </div>
    </article>
    {open ? <ScenarioDetails returnFocus={detailsButton.current} batch={batch} proposal={proposal} onClose={() => setOpen(false)} onRun={() => { setOpen(false); onRun(proposal); }} canRun={canRun} /> : null}
  </>;
}

function ScenarioDetails({ batch, proposal, onClose, onRun, canRun, returnFocus }: {
  batch: RiskAgentBatch; proposal: RiskScenarioProposal; onClose: () => void; onRun: () => void; canRun: boolean; returnFocus: HTMLElement | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previousFocus = returnFocus ?? document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => { dialog.close(); previousFocus?.focus(); };
  }, []);
  return <dialog ref={ref} className="scenario-details-modal" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="scenario-details-content">
      <header className="panel-heading"><div><p className="eyebrow">Generated scenario · {labelize(proposal.request.scenario.scenario_id)}</p><h2 id={titleId}>{proposal.title}</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Close scenario details">×</button>
      </header>
      <p className="microcopy">{proposal.request.scenario.horizon_days} days · {proposal.affectedPositions.map(compactId).join(", ") || "No directly affected position identified"}</p>
      <p className="microcopy">{batch.model} · portfolio {batch.context.portfolioId} · snapshot {batch.context.snapshotAsOf}. Generated {new Date(batch.generatedAt).toLocaleString()}. News: {batch.context.newsStatus}. Hypotheses; losses appear after a run.</p>
      {batch.limitations.length ? <p className="microcopy">{batch.limitations.join(" ")}</p> : null}
      <h3>Cause and effect</h3><ol>{proposal.causalChain.map((step, i) => <li key={i}>{step}</li>)}</ol>
      <h3>Assumptions</h3><p>{proposal.assumptions.join(" ") || "See parameter rationales below."}</p>
      {proposal.unmodeledRisks.length ? <><h3>Outside the engine</h3><p>{proposal.unmodeledRisks.join(" ")}</p></> : null}
      {proposal.sources.length ? <div>Supplied news sources: {proposal.sources.map(source => <p key={source.id}>
        <a href={/^https?:\/\//.test(source.url) ? source.url : undefined} target="_blank" rel="noreferrer">{source.title}</a> · {source.source} · {new Date(source.published_at).toLocaleString()}
      </p>)}</div> : <p className="microcopy">Hypothetical event: no news source cited.</p>}
      <details open><summary>Parameters and why they were chosen</summary>
        <table className="engine-table"><thead><tr><th>Engine parameter</th><th>Value</th><th>Basis</th></tr></thead><tbody>
          {proposal.parameters.map(parameter => <tr key={parameter.name}><td>{parameter.name}</td><td>{JSON.stringify(parameter.value)}</td><td>{parameter.source}: {parameter.rationale}</td></tr>)}
        </tbody></table>
        <small>Decimal parameters are fractions: −0.05 = −5%; 0.60 APY = 60% annual. Threshold shifts are percentage points.</small>
      </details>
      <details><summary>Exact risk-engine request</summary><pre>{JSON.stringify(proposal.request, null, 2)}</pre></details>
      <button className="primary-button" disabled={!canRun} onClick={onRun}>Run this stress case</button>
    </div>
  </dialog>;
}
