import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { loadRiskAssistantStatus, loadRiskNews } from "./data/api";
import { compactId, labelize } from "./lib/format";
import type { DataMode, RiskAgentBatch, RiskScenarioProposal } from "./lib/types";

export function RiskScenarioCards({ batch, onRun, canRun }: { batch: RiskAgentBatch; onRun: (proposal: RiskScenarioProposal) => void; canRun: boolean }) {
  return <div className="risk-agent-cards">
    <p className="microcopy">{batch.model} · portfolio {batch.context.portfolioId} · market snapshot {batch.context.snapshotAsOf}.
      Generated {new Date(batch.generatedAt).toLocaleString()}. News: {batch.context.newsStatus}. Proposed hypotheses; losses appear after a run.</p>
    {batch.limitations.length ? <p className="microcopy">{batch.limitations.join(" ")}</p> : null}
    {batch.proposals.map(proposal => <article className="risk-agent-card" key={proposal.id}>
      <p className="eyebrow">New stress case · {labelize(proposal.request.scenario.scenario_id)}</p>
      <h3>{proposal.title}</h3>
      <p className="microcopy">{proposal.request.scenario.horizon_days} days · {proposal.affectedPositions.map(compactId).join(", ") || "No directly affected position identified"}</p>
      <ol>{proposal.causalChain.map((step, i) => <li key={i}>{step}</li>)}</ol>
      <p className="microcopy"><strong>Assumptions:</strong> {proposal.assumptions.join(" ") || "See parameter rationales below."}</p>
      {proposal.unmodeledRisks.length ? <p className="microcopy"><strong>Outside the engine:</strong> {proposal.unmodeledRisks.join(" ")}</p> : null}
      {proposal.sources.length ? <div className="microcopy">Supplied news sources: {proposal.sources.map(source => <p key={source.id}>
        <a href={/^https?:\/\//.test(source.url) ? source.url : undefined} target="_blank" rel="noreferrer">{source.title}</a> · {source.source} · {new Date(source.published_at).toLocaleString()}
      </p>)}</div> : <p className="microcopy">Hypothetical event: no news source cited.</p>}
      <details><summary>Parameters and why they were chosen</summary>
        <table className="engine-table"><thead><tr><th>Engine parameter</th><th>Value</th><th>Basis</th></tr></thead><tbody>
          {proposal.parameters.map(parameter => <tr key={parameter.name}><td>{parameter.name}</td><td>{JSON.stringify(parameter.value)}</td><td>{parameter.source}: {parameter.rationale}</td></tr>)}
        </tbody></table>
        <small>Decimal parameters are fractions: −0.05 = −5%; 0.60 APY = 60% annual. Threshold shifts are percentage points.</small>
      </details>
      <details><summary>Exact risk-engine request</summary><pre>{JSON.stringify(proposal.request, null, 2)}</pre></details>
      <button className="run-card" disabled={!canRun} onClick={() => onRun(proposal)}>Run this stress case</button>
    </article>)}
  </div>;
}

export function RiskScenarioAgent({ mode, batches, onGenerate, onRun, isRunning, onApiMode }: {
  mode: DataMode; batches: RiskAgentBatch[]; onGenerate: (message: string, count: number) => void;
  onRun: (proposal: RiskScenarioProposal) => void; isRunning: boolean; onApiMode: () => void;
}) {
  const [event, setEvent] = useState("");
  const [count, setCount] = useState(3);
  const status = useQuery({ queryKey: ["risk-assistant-status"], queryFn: loadRiskAssistantStatus, enabled: mode === "api", staleTime: 30000 });
  const news = useQuery({ queryKey: ["risk-market-news"], queryFn: loadRiskNews, enabled: mode === "api", staleTime: 60000 });
  const ready = mode === "api" && status.data?.configured;
  return <section className="visual-panel risk-scenario-agent" aria-label="Market-event risk scenario agent">
    <p className="eyebrow">Risk scenario agent · Gemini API</p>
    <h2>What could challenge this portfolio?</h2>
    <p className="microcopy">Describe a market event. The model connects it to this portfolio and proposes up to three named stresses, with explicit assumptions. The risk engine calculates their impact when you run them.</p>
    {mode !== "api" ? <button className="run-card" onClick={onApiMode}>Switch to Engine API for generated scenarios</button> : null}
    {status.isError ? <p role="alert">Could not reach the risk assistant backend.</p> : null}
    {status.data && !status.data.configured ? <p role="alert">Set GEMINI_API_KEY on the backend to enable scenario generation.</p> : null}
    <div className="risk-agent-examples">
      {["Si les États-Unis baissent les taux, quels stress pourraient toucher mes positions ?", "Si le dollar se déprécie face à l’euro, en quoi mon portefeuille est-il exposé ?", "Propose trois scénarios adverses adaptés aux positions de mon portefeuille."].map(prompt => <button key={prompt} onClick={() => setEvent(prompt)}>{prompt}</button>)}
    </div>
    <form onSubmit={e => { e.preventDefault(); if (ready && event.trim()) onGenerate(event.trim(), count); }}>
      <label>Market event or question<textarea value={event} onChange={e => setEvent(e.target.value)} maxLength={6000} rows={3} placeholder="A Fed rate cut, weaker dollar, funding reversal, or an article…" /></label>
      <label>Number of proposed cases<select value={count} onChange={e => setCount(Number(e.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></label>
      <button className="run-card" disabled={!ready || !event.trim()}>Generate in chatbot</button>
    </form>
    <p className="microcopy">News feed: {news.isError ? "unavailable — no headlines invented" : news.data?.status ?? "loading"}.
      {news.data?.status === "not_configured" ? " Your news API is not connected yet; typed events are hypothetical." : ""}</p>
    {news.data?.articles.length ? <>
      <details><summary>{news.data.articles.length} supplied market articles</summary>{news.data.articles.map(article => <p key={article.id}><a href={article.url} target="_blank" rel="noreferrer">{article.title}</a> · {article.source} · {new Date(article.published_at).toLocaleString()}</p>)}</details>
      <button className="run-card" disabled={!ready} onClick={() => onGenerate("Analyse les news fournies et propose des scénarios qui challengent les positions de mon portefeuille. Cite les articles utilisés et sépare faits rapportés et hypothèses.", count)}>Generate from supplied news</button>
    </> : null}
    {batches.map(batch => <RiskScenarioCards key={batch.generatedAt} batch={batch} onRun={onRun} canRun={mode === "api" && !isRunning} />)}
  </section>;
}
