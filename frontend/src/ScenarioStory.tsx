/**
 * Scenario story: one run of the risk engine told in chapters, each a button that reveals its
 * explanation and a motion chart (impact, mechanisms, positions, liquidation, uncertainty, severity).
 *
 * Every number comes from the run on screen (risk_result + risk_analytics); nothing is invented.
 * Motion follows theme/motion.css: copy blurs in, bars grow on springs, lines draw themselves,
 * markers glide to their value, tags open from a slit. A chart zooms through a View Transition.
 * Keys: 1-6 pick a chapter, ←/→ step, Esc closes the zoom.
 */
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Maximize2, Pause, Play, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { COMPONENT_COPY, COMPONENT_SHORT } from "./lib/lossComponents";
import { compactId, labelize, money, percent } from "./lib/format";
import type { AppData, RiskPosition } from "./lib/types";
import { EASE, Figure, InteractiveLabel, SPRING, reveal, withViewTransition } from "./motion/primitives";
import "./scenario-story.css";

type Summary = { p05_usd: string; p25_usd: string; p50_usd: string; p75_usd: string; p95_usd: string; base_usd: string };
type Uncertainty = { draws: number; portfolio: Summary; histogram: Array<{ from_usd: string; to_usd: string; draws: number }> };
type Curves = { x_param: string; x_values: string[]; total_usd: string[] };
type ChapterId = "impact" | "mechanisms" | "positions" | "liquidation" | "uncertainty" | "severity";
type Chapter = { id: ChapterId; label: string; title: string; copy: string[]; method: string; caption: string };

const PLAY_MS = 5200;

/** "usde_spot_shock_pct" -> "USDe spot shock". */
const paramName = (param: string) =>
  labelize(param.replace(/_pct$/, "")).replace(/\bsusde\b/gi, "sUSDe").replace(/\busde\b/gi, "USDe");

export function ScenarioStory({ data }: { data: AppData }) {
  const risk = data.risk;
  const analytics = data.analytics as (AppData["analytics"] & { uncertainty?: Uncertainty; position_curves?: Curves | null }) | null;
  // App passes a fresh `data` object on every render: memoise on the engine outputs it wraps.
  const facts = useMemo(() => storyFacts(risk), [risk]);
  const chapters = useMemo(() => buildChapters(facts, analytics?.uncertainty ?? null, analytics?.position_curves ?? null),
    [facts, analytics]);
  const chapterIds = chapters.map((c) => c.id).join(",");
  const [active, setActive] = useState<ChapterId>("impact");
  const [playing, setPlaying] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const [methodOpen, setMethodOpen] = useState(false);
  const chapter = chapters.find((c) => c.id === active) ?? chapters[0];
  const index = chapters.indexOf(chapter);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  const go = (id: ChapterId) => {
    setActive(id);
    setMethodOpen(false);
  };
  const step = (delta: number) => go(chapters[(index + delta + chapters.length) % chapters.length].id);

  // Play: advance every PLAY_MS, stop after the last chapter.
  useEffect(() => {
    if (!playing) return;
    const ids = chapterIds.split(",") as ChapterId[];
    const timer = window.setTimeout(() => {
      if (index >= ids.length - 1) setPlaying(false);
      else go(ids[index + 1]);
    }, PLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, index, chapterIds]);

  // Keyboard: 1-6 and arrows, never while typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (event.metaKey || event.ctrlKey || event.altKey || target?.closest("input, textarea, select, [contenteditable]")) return;
      if (event.key === "Escape" && zoomed) return closeZoom();
      const n = Number(event.key);
      if (n >= 1 && n <= chapters.length) {
        setPlaying(false);
        go(chapters[n - 1].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const openZoom = () => withViewTransition(() => setZoomed(true));
  const closeZoom = () => withViewTransition(() => setZoomed(false));

  const chart = (big: boolean) => (
    <StoryChart id={chapter.id} facts={facts} big={big} uncertainty={analytics?.uncertainty ?? null}
      curves={analytics?.position_curves ?? null} />
  );

  return (
    <section className="visual-panel story" aria-label="Scenario story">
      <header className="story-head">
        <div>
          <p className="eyebrow">Scenario story · {labelize(String(risk.scenario_id))} · {risk.horizon_days}-day horizon</p>
          <h2 className="story-figure-line">
            <Figure value={facts.total} className="story-figure" />
            <span className="story-figure-unit">conditional loss</span>
          </h2>
          <p className="story-sub">
            {facts.before > 0 ? <>{percent(facts.total / facts.before, 2)} of {money(facts.before)} net equity · </> : null}
            {chapters.length} chapters · press 1–{chapters.length}
          </p>
        </div>
        <button className="np-button story-play" onClick={() => {
          if (!playing && index === chapters.length - 1) go(chapters[0].id);
          setPlaying(!playing);
        }} aria-pressed={playing}>
          {playing ? <Pause size={13} /> : <Play size={13} />}
          <InteractiveLabel>{playing ? "Pause story" : "Play story"}</InteractiveLabel>
        </button>
      </header>
      <hr className="np-rule" />

      <div className="story-body">
        <nav className="story-chapters" role="tablist" aria-label="Story chapters"
          onKeyDown={(event) => {
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
            event.preventDefault();
            const next = (index + (event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1) + chapters.length) % chapters.length;
            go(chapters[next].id);
            tabs.current[next]?.focus();
          }}>
          {chapters.map((c, i) => (
            <button key={c.id} ref={(el) => { tabs.current[i] = el; }} role="tab" id={`story-tab-${c.id}`}
              aria-selected={c.id === active} aria-controls="story-stage" tabIndex={c.id === active ? 0 : -1}
              className="story-chapter" data-selected={c.id === active}
              onClick={() => { setPlaying(false); go(c.id); }}>
              <InteractiveLabel>{c.label}</InteractiveLabel>
              <span className="story-chapter-key">[{i + 1}]</span>
              {playing && c.id === active ? (
                <motion.span key={`${c.id}-progress`} className="story-progress" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }}
                  transition={{ duration: PLAY_MS / 1000, ease: "linear" }} />
              ) : null}
            </button>
          ))}
        </nav>

        <div className="story-stage" id="story-stage" role="tabpanel" aria-labelledby={`story-tab-${active}`}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={chapter.id} className="story-scene">
              <div className="story-copy">
                <motion.p className="story-index" {...reveal(0)}>{String(index + 1).padStart(2, "0")} / {String(chapters.length).padStart(2, "0")}</motion.p>
                <motion.h3 {...reveal(0.015)}>{chapter.title}</motion.h3>
                {chapter.copy.map((text, i) => <motion.p key={i} {...reveal(0.035 + i * 0.045)}>{text}</motion.p>)}
                <motion.div {...reveal(0.12)}>
                  <button className="np-button" aria-expanded={methodOpen} onClick={() => setMethodOpen(!methodOpen)}>
                    <InteractiveLabel>{methodOpen ? "Hide the method" : "How it is computed"}</InteractiveLabel>
                  </button>
                </motion.div>
                <AnimatePresence initial={false}>
                  {methodOpen ? (
                    <motion.p key="method" className="story-method"
                      initial={{ opacity: 0, height: 0, filter: "blur(8px)" }}
                      animate={{ opacity: 1, height: "auto", filter: "blur(0px)", transition: { duration: 0.46, ease: EASE } }}
                      exit={{ opacity: 0, height: 0, filter: "blur(8px)", transition: { duration: 0.24, ease: "easeInOut" as const } }}>
                      {chapter.method}
                    </motion.p>
                  ) : null}
                </AnimatePresence>
              </div>
              <motion.figure className="story-chart" {...reveal(0.06)}
                style={{ viewTransitionName: zoomed ? undefined : "section-preview" } as CSSProperties}>
                {chart(false)}
                <figcaption>
                  <span>{chapter.caption}</span>
                  <button className="story-zoom-button" onClick={openZoom} aria-label="Zoom into this chart">
                    <Maximize2 size={12} /> <InteractiveLabel>Zoom</InteractiveLabel>
                  </button>
                </figcaption>
              </motion.figure>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {zoomed ? createPortal(
        <div className="story-zoom" role="dialog" aria-modal="true" aria-label={chapter.title} onClick={closeZoom}>
          <figure className="story-zoom-figure" style={{ viewTransitionName: "section-preview" } as CSSProperties}
            onClick={(event) => event.stopPropagation()}>
            <header>
              <div>
                <p className="eyebrow">{String(index + 1).padStart(2, "0")} · {chapter.label}</p>
                <h3>{chapter.title}</h3>
              </div>
              <button className="np-button" onClick={closeZoom} autoFocus>
                <X size={13} /> <InteractiveLabel>Close</InteractiveLabel> <span className="story-chapter-key">[Esc]</span>
              </button>
            </header>
            {chart(true)}
            <figcaption>{chapter.copy.join(" ")} {chapter.method}</figcaption>
          </figure>
        </div>,
        document.body,
      ) : null}
    </section>
  );
}

// Facts and chapters -----------------------------------------------------------------------
type Mechanism = { key: string; value: number };
type Facts = {
  scenario: string;
  horizon: number;
  before: number;
  after: number;
  total: number;
  penalty: number;
  mechanisms: Mechanism[];
  positions: Array<{ id: string; before: number; after: number; loss: number; position: RiskPosition }>;
  borrows: RiskPosition[];
};

function storyFacts(risk: AppData["risk"]): Facts {
  const before = risk.positions.reduce((s, p) => s + Number(p.net_equity_before_usd), 0);
  const penalty = Number(risk.portfolio.shared_liquidity_penalty_usd ?? 0);
  const total = risk.portfolio.total_conditional_loss_usd === null
    ? risk.positions.reduce((s, p) => s + Number(p.conditional_loss_usd), 0) + penalty
    : Number(risk.portfolio.total_conditional_loss_usd);
  const sums: Record<string, number> = {};
  for (const p of risk.positions) for (const [k, v] of Object.entries(p.loss_components)) sums[k] = (sums[k] ?? 0) + Number(v);
  if (penalty) sums.shared_liquidity_penalty = penalty;
  const mechanisms = Object.entries(sums).filter(([, v]) => Math.abs(v) >= 0.005)
    .map(([key, value]) => ({ key, value })).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  return {
    scenario: labelize(String(risk.scenario_id)),
    horizon: risk.horizon_days,
    before,
    after: before - total,
    total,
    penalty,
    mechanisms,
    positions: risk.positions.map((p) => ({
      id: p.position_id, before: Number(p.net_equity_before_usd), after: Number(p.net_equity_after_usd),
      loss: Number(p.conditional_loss_usd), position: p,
    })),
    borrows: risk.positions.filter((p) => p.risk_metric),
  };
}

function buildChapters(f: Facts, uncertainty: Uncertainty | null, curves: Curves | null): Chapter[] {
  const share = (v: number) => (f.total ? percent(v / f.total, 0) : "n/a");
  const top = f.mechanisms[0];
  const losers = f.positions.filter((p) => p.loss > 0.5).sort((a, b) => b.loss - a.loss);
  const capped = f.mechanisms.some((m) => m.key === "limited_liability");
  const chapters: Chapter[] = [
    {
      id: "impact", label: "Impact", title: "What this scenario costs",
      copy: [
        `If the ${f.scenario} happens, the portfolio loses ${money(f.total)}${f.before > 0 ? `, ${percent(f.total / f.before, 2)} of its ${money(f.before)} net equity` : ""}.`,
        `Net equity goes from ${money(f.before)} to ${money(f.after)} over a ${f.horizon}-day horizon. It is a conditional loss: the engine never says how likely the scenario is.`,
      ],
      method: "Loss = net equity before − net equity after, summed over positions, plus the shared exit-venue penalty that exists only at portfolio level.",
      caption: "Net equity before, the part the scenario takes, and what is left",
    },
    {
      id: "mechanisms", label: "Mechanisms", title: "Why it loses",
      copy: top ? [
        `${COMPONENT_COPY[top.key] ?? labelize(top.key)} is the largest driver: ${money(top.value)}, ${share(top.value)} of the loss.`,
        f.mechanisms.length > 1
          ? `${f.mechanisms.length} mechanisms in total, each computed once, so nothing is counted twice.${capped ? " The equity cap is a relief: a borrow position cannot lose more than its equity, the shortfall falls on its lenders." : ""}`
          : "A single mechanism explains the whole loss.",
      ] : ["No mechanism moves the portfolio in this scenario."],
      method: "Each position's loss is split by mechanism: market repricing, backing loss, liquidation penalty, exit cost, carry, bad debt. Bars going up are gains or caps.",
      caption: "Waterfall from net equity before to net equity after, one bar per mechanism",
    },
    {
      id: "positions", label: "Positions", title: "Who carries it",
      copy: losers.length ? [
        `${losers.length} of ${f.positions.length} positions lose money; ${compactId(losers[0].id)} carries ${share(losers[0].loss)} of the loss.`,
        "Click a position to open its mechanisms and its liquidation metric.",
      ] : ["No position loses money in this scenario.", "Click a position to open its details."],
      method: "Net equity is collateral minus debt for borrow positions and market value for holdings. Before uses the recorded snapshot; after applies the scenario.",
      caption: "Net equity per position: before (grey), after (ink), loss (red)",
    },
  ];
  if (f.borrows.length) {
    const broken = f.borrows.filter((p) => p.risk_metric?.liquidatable);
    chapters.push({
      id: "liquidation", label: "Liquidation", title: "How close to liquidation",
      copy: [
        broken.length
          ? `${broken.length} of ${f.borrows.length} borrow positions cross their liquidation threshold: ${broken.map((p) => compactId(p.position_id)).join(", ")}.`
          : `None of the ${f.borrows.length} borrow positions crosses its liquidation threshold.`,
        "Each marker glides from its value before the shock to its value after it; the hatched zone is where liquidators can act.",
      ],
      method: "Aave: health factor = oracle collateral × liquidation threshold / debt, liquidatable below 1. Morpho: LTV = debt / oracle collateral, liquidatable above its LLTV. An oracle only sees the share of the market move it passes through.",
      caption: "Liquidation metric before → after, against each market's threshold",
    });
  }
  if (uncertainty) {
    const pf = uncertainty.portfolio;
    chapters.push({
      id: "uncertainty", label: "Uncertainty", title: "How sure is the number",
      copy: [
        `Re-run ${uncertainty.draws} times with uncertain model inputs, the loss stays between ${money(pf.p05_usd)} and ${money(pf.p95_usd)} in 90% of runs; the median is ${money(pf.p50_usd)}.`,
        "It measures what we do not know about the model, not how likely the scenario is.",
      ],
      method: "The scenario stays fixed; unverified inputs (oracle pass-through, liquidation thresholds, venue depth, sUSDe beta) are drawn within their ranges. Verified inputs never vary.",
      caption: "Portfolio loss across model runs, with P5, median, P95 and this run",
    });
  }
  if (curves && curves.x_values.length > 1) {
    const losses = curves.total_usd.map(Number);
    const worst = losses.indexOf(Math.max(...losses));
    chapters.push({
      id: "severity", label: "Severity", title: "What if it is worse",
      copy: [
        `Each bar is a full engine run at another ${paramName(curves.x_param)}. At ${percent(curves.x_values[worst], 0)}, the loss reaches ${money(losses[worst])}.`,
        "Hover the chart to read any point; the pulsing dot is the closest point to this run.",
      ],
      method: "Same portfolio, same market snapshot, one complete engine run per severity point.",
      caption: `Portfolio loss along the ${paramName(curves.x_param)}`,
    });
  }
  return chapters;
}

// Charts --------------------------------------------------------------------------------------
function StoryChart({ id, facts, big, uncertainty, curves }: {
  id: ChapterId; facts: Facts; big: boolean; uncertainty: Uncertainty | null; curves: Curves | null;
}) {
  if (id === "impact") return <ImpactChart facts={facts} />;
  if (id === "mechanisms") return <WaterfallChart facts={facts} big={big} />;
  if (id === "positions") return <PositionsChart facts={facts} />;
  if (id === "liquidation") return <LiquidationChart positions={facts.borrows} />;
  if (id === "uncertainty" && uncertainty) return <UncertaintyChart uncertainty={uncertainty} total={facts.total} big={big} />;
  if (id === "severity" && curves) return <SeverityChart curves={curves} total={facts.total} big={big} />;
  return null;
}

/** Hover tag positioned over a chart in percentages of its box. */
function ChartTag({ x, y, children, tone = "ink" }: { x: number; y: number; children: ReactNode; tone?: string }) {
  return <span className="np-tag story-hover-tag" data-tone={tone} style={{ left: `${x}%`, top: `${y}%` }}>{children}</span>;
}

function ImpactChart({ facts }: { facts: Facts }) {
  const scale = Math.max(facts.before, facts.after, 1);
  const after = Math.max(facts.after, 0) / scale;
  const loss = Math.max(facts.total, 0) / scale;
  const gain = facts.total < 0;
  return (
    <div className="impact-chart">
      <div className="impact-track">
        <motion.div className="impact-after" initial={{ width: "100%" }} animate={{ width: `${after * 100}%` }}
          transition={{ duration: 1.1, ease: EASE, delay: 0.35 }} />
        {!gain ? (
          <motion.div className="impact-loss" initial={{ width: 0, opacity: 0 }} animate={{ width: `${loss * 100}%`, opacity: 1 }}
            transition={{ duration: 1.1, ease: EASE, delay: 0.35 }} />
        ) : null}
        <motion.span className="impact-marker" initial={{ left: "100%" }} animate={{ left: `${after * 100}%` }}
          transition={{ duration: 1.1, ease: EASE, delay: 0.35 }} />
      </div>
      <div className="impact-legend">
        <div><span>Net equity before</span><Figure value={facts.before} delay={0.1} /></div>
        <div data-tone={gain ? "gain" : "loss"}><span>{gain ? "Gain" : "Loss"}</span><Figure value={Math.abs(facts.total)} delay={0.35} /></div>
        <div><span>Net equity after</span><Figure value={facts.after} delay={0.6} /></div>
      </div>
      {facts.before > 0 ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.35 }}>
          <span className="np-tag" data-tone={gain ? "green" : undefined} style={{ animationDelay: "1.35s" }}>
            {gain ? "+" : "−"}{percent(Math.abs(facts.total) / facts.before, 2)} of equity
          </span>
        </motion.div>
      ) : null}
    </div>
  );
}

function WaterfallChart({ facts, big }: { facts: Facts; big: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = big ? 340 : 280, top = 28, bottom = 44, left = 8, right = 8;
  const mechanisms = facts.mechanisms.length > 6
    ? [...facts.mechanisms.slice(0, 5), { key: "other", value: facts.mechanisms.slice(5).reduce((s, m) => s + m.value, 0) }]
    : facts.mechanisms;
  let running = facts.before;
  const bars = [
    { label: "Before", full: "Net equity before", from: 0, to: facts.before, kind: "total" as const },
    ...mechanisms.map((m) => {
      const from = running;
      running -= m.value;
      return { label: COMPONENT_SHORT[m.key] ?? labelize(m.key), full: COMPONENT_COPY[m.key] ?? "Other mechanisms", from, to: running,
        kind: m.value >= 0 ? "loss" as const : "gain" as const };
    }),
    { label: "After", full: "Net equity after", from: 0, to: facts.after, kind: "total" as const },
  ];
  // Zoom the axis on the part that moves: small losses next to a large equity would otherwise vanish.
  // Totals are then drawn from the chart's floor with a break mark, and the caption says where the axis starts.
  const moving = bars.filter((b) => b.kind !== "total").flatMap((b) => [b.from, b.to]).concat(facts.before, facts.after);
  const hi = Math.max(...moving, 1);
  const low = Math.min(...moving);
  const lo = Math.min(Math.max(0, low - (hi - low) * 1.4), low);
  const broken = lo > 0;
  const y = (v: number) => top + ((hi - Math.max(v, lo)) / (hi - lo || 1)) * (H - top - bottom);
  const band = (W - left - right) / bars.length, bw = Math.min(56, band * 0.56);
  const x = (i: number) => left + band * i + (band - bw) / 2;
  const gap = 0.14;
  // Totals are labelled above their bar, mechanisms under theirs (the connector runs along their top).
  const labelY = (b: { kind: string }, y1: number, h: number) => (b.kind === "total" ? y1 - 8 : y1 + h + 14);

  return (
    <div className="story-svg-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="story-svg" role="img"
        aria-label={`Waterfall: ${bars.map((b) => `${b.full} ${money(b.kind === "total" ? b.to : b.from - b.to)}`).join(", ")}`}>
        <line x1={left} x2={W - right} y1={y(lo)} y2={y(lo)} className="axis" />
        {bars.map((b, i) => {
          const y1 = y(Math.max(b.from, b.to)), h = Math.max(Math.abs(y(b.from) - y(b.to)), 1.5);
          const start = b.kind === "total" ? y(lo) : y(b.from);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x(i) - (band - bw) / 2} y={top} width={band} height={H - top - bottom} className="hit" />
              <motion.rect x={x(i)} width={bw} className={`bar bar-${b.kind}`} data-dim={hover !== null && hover !== i}
                initial={{ y: start, height: 0 }} animate={{ y: y1, height: h }}
                transition={{ ...SPRING, delay: 0.15 + i * gap }} />
              {broken && b.kind === "total" ? (
                <motion.path d={`M${x(i) - 3},${y(lo) - 9} l${bw + 6},-6 M${x(i) - 3},${y(lo) - 4} l${bw + 6},-6`} className="break"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 + i * gap }} />
              ) : null}
              {i < bars.length - 1 ? (
                <motion.line x1={x(i) + bw} x2={x(i + 1)} y1={y(b.to)} y2={y(b.to)} className="connector"
                  initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }}
                  transition={{ duration: 0.3, ease: EASE, delay: 0.35 + i * gap }} />
              ) : null}
              <motion.text x={x(i) + bw / 2} y={H - bottom + 18} className="label" textAnchor="middle"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 + i * gap }}>{b.label}</motion.text>
              <motion.text x={x(i) + bw / 2} y={labelY(b, y1, h)} className="value" textAnchor="middle"
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.45 + i * gap, duration: 0.3 }}>
                {b.kind === "total" ? money(b.to) : `${b.kind === "loss" ? "−" : "+"}${money(Math.abs(b.from - b.to))}`}
              </motion.text>
            </g>
          );
        })}
      </svg>
      {broken ? <p className="story-axis-note">Axis starts at {money(lo)} so each mechanism stays visible; the totals are cut (≈).</p> : null}
      {hover !== null ? (
        <ChartTag x={((x(hover) + bw / 2) / W) * 100} y={(y(Math.max(bars[hover].from, bars[hover].to)) / H) * 100 - 12}
          tone={bars[hover].kind === "loss" ? "red" : bars[hover].kind === "gain" ? "green" : "ink"}>
          {bars[hover].full}
        </ChartTag>
      ) : null}
    </div>
  );
}

function PositionsChart({ facts }: { facts: Facts }) {
  const [open, setOpen] = useState<string | null>(null);
  const max = Math.max(1, ...facts.positions.flatMap((p) => [p.before, p.after]));
  const rows = [...facts.positions].sort((a, b) => b.loss - a.loss);
  return (
    <div className="position-bars">
      {rows.map((p, i) => {
        const b = Math.max(p.before, 0) / max, a = Math.max(p.after, 0) / max;
        const isOpen = open === p.id;
        const components = Object.entries(p.position.loss_components).map(([k, v]) => [k, Number(v)] as const)
          .filter(([, v]) => Math.abs(v) >= 0.005).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
        const cmax = Math.max(1, ...components.map(([, v]) => Math.abs(v)));
        const metric = p.position.risk_metric;
        return (
          <div key={p.id} className="position-bar" data-open={isOpen}>
            <button className="position-bar-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : p.id)}>
              <InteractiveLabel>{compactId(p.id)}</InteractiveLabel>
              <span className="position-bar-track">
                <span className="position-bar-before" style={{ width: `${b * 100}%` }} />
                <motion.span className="position-bar-after" initial={{ width: `${b * 100}%` }} animate={{ width: `${a * 100}%` }}
                  transition={{ duration: 1, ease: EASE, delay: 0.25 + i * 0.08 }} />
                {p.loss > 0 ? (
                  <motion.span className="position-bar-loss" style={{ left: `${a * 100}%` }} initial={{ width: 0, opacity: 0 }}
                    animate={{ width: `${Math.max(b - a, 0) * 100}%`, opacity: 1 }} transition={{ duration: 1, ease: EASE, delay: 0.25 + i * 0.08 }} />
                ) : null}
              </span>
              <span className="position-bar-value" data-tone={p.loss > 0.5 ? "loss" : p.loss < -0.5 ? "gain" : "flat"}>
                {p.loss > 0.5 ? "−" : p.loss < -0.5 ? "+" : ""}{money(Math.abs(p.loss))}
              </span>
            </button>
            <AnimatePresence initial={false}>
              {isOpen ? (
                <motion.div className="position-bar-detail" initial={{ height: 0, opacity: 0, filter: "blur(8px)" }}
                  animate={{ height: "auto", opacity: 1, filter: "blur(0px)", transition: { duration: 0.46, ease: EASE } }}
                  exit={{ height: 0, opacity: 0, filter: "blur(8px)", transition: { duration: 0.24, ease: "easeInOut" as const } }}>
                  <p>Net equity {money(p.before)} → {money(p.after)}{metric ? ` · ${labelize(metric.type)} ${Number(metric.before).toFixed(3)} → ${Number(metric.after).toFixed(3)}${metric.liquidatable ? " · liquidatable" : ""}` : ""}</p>
                  {components.map(([k, v], j) => (
                    <div key={k} className="component-row">
                      <span>{COMPONENT_COPY[k] ?? labelize(k)}</span>
                      <span className="component-track">
                        <motion.span data-gain={v < 0} initial={{ scaleX: 0 }} animate={{ scaleX: Math.abs(v) / cmax }}
                          transition={{ ...SPRING, delay: 0.1 + j * 0.06 }} />
                      </span>
                      <strong>{money(v)}</strong>
                    </div>
                  ))}
                  {!components.length ? <p className="muted">No loss component for this position.</p> : null}
                  {p.position.warnings[0] ? <p className="microcopy">{p.position.warnings[0]}</p> : null}
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

function LiquidationChart({ positions }: { positions: RiskPosition[] }) {
  return (
    <div className="gauges">
      {positions.map((p, i) => {
        const m = p.risk_metric!;
        const before = Number(m.before), after = Number(m.after), threshold = Number(m.threshold);
        const isHf = m.type === "health_factor";
        const lo = isHf ? Math.min(threshold, before, after) * 0.85 : 0;
        const hi = Math.max(before, after, threshold) * (isHf ? 1.08 : 1.12);
        const pos = (v: number) => Math.min(Math.max(((v - lo) / (hi - lo)) * 100, 0), 100);
        const delay = 0.35 + i * 0.15;
        const toward = isHf ? after < before : after > before;
        return (
          <div key={p.position_id} className="gauge">
            <div className="gauge-head">
              <span>{compactId(p.position_id)}</span>
              <span className="muted">{labelize(m.type)} {before.toFixed(3)} → {after.toFixed(3)} · liquidation {isHf ? "below" : "above"} {threshold.toFixed(isHf ? 2 : 3)}</span>
            </div>
            <div className="gauge-track">
              <span className="gauge-danger" style={isHf ? { left: 0, width: `${pos(threshold)}%` } : { left: `${pos(threshold)}%`, right: 0 }} />
              <span className="gauge-threshold" style={{ left: `${pos(threshold)}%` }} />
              <motion.span className="gauge-trail" data-toward={toward}
                initial={{ left: `${pos(before)}%`, width: 0 }}
                animate={{ left: `${Math.min(pos(before), pos(after))}%`, width: `${Math.abs(pos(after) - pos(before))}%` }}
                transition={{ ...SPRING, delay }} />
              <span className="gauge-ghost" style={{ left: `${pos(before)}%` }} />
              <motion.span className="gauge-marker" data-liquidatable={m.liquidatable}
                initial={{ left: `${pos(before)}%` }} animate={{ left: `${pos(after)}%` }} transition={{ ...SPRING, delay }} />
            </div>
            <motion.div className="gauge-foot" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: delay + 0.8 }}>
              <span className="np-tag" data-tone={m.liquidatable ? undefined : "blue"} style={{ animationDelay: `${delay + 0.8}s` }}>
                {m.liquidatable ? "Liquidatable" : "Safe"}
              </span>
              <span className="muted">
                {m.liquidatable ? "Threshold crossed after the shock." : `Room left: ${percent(m.distance_to_liquidation_after_pct, 1)} further oracle drop (was ${percent(m.distance_to_liquidation_before_pct, 1)}).`}
              </span>
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}

function UncertaintyChart({ uncertainty, total, big }: { uncertainty: Uncertainty; total: number; big: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const bins = uncertainty.histogram;
  const W = 640, H = big ? 300 : 220, top = 8, bottom = 30;
  const x0 = Number(bins[0]?.from_usd ?? 0), x1 = Number(bins[bins.length - 1]?.to_usd ?? 1);
  const span = x1 - x0 || 1;
  const xv = (v: number) => ((v - x0) / span) * W;
  const maxDraws = Math.max(1, ...bins.map((b) => b.draws));
  const pf = uncertainty.portfolio;
  const markers = [
    { key: "P5", v: Number(pf.p05_usd), tone: "ink" },
    { key: "Median", v: Number(pf.p50_usd), tone: "ink" },
    { key: "P95", v: Number(pf.p95_usd), tone: "ink" },
    { key: "This run", v: total, tone: "blue" },
  ];
  const yb = (d: number) => top + (1 - d / maxDraws) * (H - top - bottom);
  return (
    <div>
      <MarkerTags markers={markers.map((m, i) => ({ ...m, at: xv(m.v) / W, delay: 0.9 + i * 0.12 }))} />
      <div className="story-svg-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="story-svg" role="img"
        aria-label={`Loss distribution over ${uncertainty.draws} runs: P5 ${money(pf.p05_usd)}, median ${money(pf.p50_usd)}, P95 ${money(pf.p95_usd)}`}>
        <line x1={0} x2={W} y1={H - bottom} y2={H - bottom} className="axis" />
        {bins.map((b, i) => {
          const bx = xv(Number(b.from_usd)), bw = Math.max(xv(Number(b.to_usd)) - bx - 2, 1);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={bx} y={top} width={bw + 2} height={H - top - bottom} className="hit" />
              <motion.rect x={bx + 1} width={bw} className="bar bar-dist" data-dim={hover !== null && hover !== i}
                initial={{ y: H - bottom, height: 0 }} animate={{ y: yb(b.draws), height: H - bottom - yb(b.draws) }}
                transition={{ ...SPRING, delay: 0.1 + i * 0.025 }} />
            </g>
          );
        })}
        {markers.map((m, i) => (
          <motion.line key={m.key} x1={xv(m.v)} x2={xv(m.v)} y1={top - 6} y2={H - bottom} className={`marker marker-${m.tone}`}
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5, ease: EASE, delay: 0.7 + i * 0.12 }} />
        ))}
        <text x={0} y={H - 8} className="label">{money(x0)}</text>
        <text x={W} y={H - 8} className="label" textAnchor="end">{money(x1)}</text>
      </svg>
      {hover !== null ? (
        <ChartTag x={((xv(Number(bins[hover].from_usd)) + xv(Number(bins[hover].to_usd))) / 2 / W) * 100}
          y={(yb(bins[hover].draws) / H) * 100 - 10}>
          {bins[hover].draws} runs · {money(bins[hover].from_usd)}–{money(bins[hover].to_usd)}
        </ChartTag>
      ) : null}
      </div>
    </div>
  );
}

/**
 * Value tags above a chart, one per marker. Tags that would overlap go on the next row, and tags near
 * an edge anchor inwards so they never leave the figure.
 */
function MarkerTags({ markers }: { markers: Array<{ key: string; v: number; tone: string; at: number; delay: number }> }) {
  const MIN_GAP = 0.2; // share of the width one tag needs
  const rows: number[][] = [];
  const placed = [...markers].sort((a, b) => a.at - b.at).map((m) => {
    let row = rows.findIndex((r) => r.every((at) => Math.abs(at - m.at) >= MIN_GAP));
    if (row < 0) row = rows.push([]) - 1;
    rows[row].push(m.at);
    return { ...m, row };
  });
  return (
    <div className="story-marker-strip" style={{ height: rows.length * 24 }}>
      {placed.map((m) => (
        <span key={m.key} className="np-tag story-marker-tag" data-tone={m.tone === "blue" ? "blue" : "ink"}
          data-edge={m.at < 0.12 ? "start" : m.at > 0.88 ? "end" : undefined}
          style={{ left: `${m.at * 100}%`, top: m.row * 24, animationDelay: `${m.delay}s` }}>
          {m.key} {money(m.v)}
        </span>
      ))}
    </div>
  );
}

function SeverityChart({ curves, total, big }: { curves: Curves; total: number; big: boolean }) {
  const reduce = useReducedMotion();
  const [hover, setHover] = useState<number | null>(null);
  const points = curves.x_values.map((x, i) => ({ x: Number(x), loss: Number(curves.total_usd[i]) })).sort((a, b) => a.x - b.x);
  const W = 640, H = big ? 320 : 250, top = 24, bottom = 30, pad = 10;
  const xs = points.map((p) => p.x), ls = points.map((p) => p.loss);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), lmax = Math.max(1, ...ls), lmin = Math.min(0, ...ls);
  const px = (x: number) => pad + ((x - xmin) / (xmax - xmin || 1)) * (W - 2 * pad);
  const py = (l: number) => top + ((lmax - l) / (lmax - lmin)) * (H - top - bottom);
  const line = points.map((p, i) => `${i ? "L" : "M"}${px(p.x)},${py(p.loss)}`).join(" ");
  const area = `${line} L${px(points[points.length - 1].x)},${py(0)} L${px(points[0].x)},${py(0)} Z`;
  const run = points.reduce((best, p, i) => (Math.abs(p.loss - total) < Math.abs(points[best].loss - total) ? i : best), 0);
  const ref = useRef<SVGSVGElement>(null);
  const onMove = (event: PointerEvent) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const vx = ((event.clientX - rect.left) / rect.width) * W;
    setHover(points.reduce((best, p, i) => (Math.abs(px(p.x) - vx) < Math.abs(px(points[best].x) - vx) ? i : best), 0));
  };
  const barW = Math.max(2, Math.min(6, (W / points.length) * 0.18));
  return (
    <div className="story-svg-wrap">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="story-svg" role="img" onPointerMove={onMove} onPointerLeave={() => setHover(null)}
        aria-label={`Loss along ${paramName(curves.x_param)}: ${points.map((p) => `${percent(p.x, 0)} ${money(p.loss)}`).join(", ")}`}>
        <line x1={0} x2={W} y1={py(0)} y2={py(0)} className="axis" />
        {points.map((p, i) => (
          <motion.rect key={i} x={px(p.x) - barW / 2} width={barW} className="bar bar-rail" data-run={i === run}
            initial={{ y: py(0), height: 0 }} animate={{ y: Math.min(py(p.loss), py(0)), height: Math.abs(py(0) - py(p.loss)) }}
            transition={{ ...SPRING, delay: 0.05 + i * 0.03 }} />
        ))}
        <motion.path d={area} className="area" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.9, duration: 0.6 }} />
        <motion.path d={line} className="curve" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
          transition={{ duration: 1.2, ease: EASE, delay: 0.25 }} />
        {!reduce ? (
          <motion.circle cx={px(points[run].x)} cy={py(points[run].loss)} className="pulse"
            initial={{ r: 4, opacity: 0.55 }} animate={{ r: 14, opacity: 0 }} transition={{ duration: 1.6, repeat: Infinity, delay: 1.4 }} />
        ) : null}
        <motion.circle cx={px(points[run].x)} cy={py(points[run].loss)} r={4.5} className="dot dot-run"
          initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ ...SPRING, delay: 1.3 }} />
        {hover !== null ? (
          <g className="scrub">
            <line x1={px(points[hover].x)} x2={px(points[hover].x)} y1={top} y2={py(0)} />
            <circle cx={px(points[hover].x)} cy={py(points[hover].loss)} r={4} />
          </g>
        ) : null}
        <text x={pad} y={H - 8} className="label">{percent(xmin, 0)}</text>
        <text x={W - pad} y={H - 8} className="label" textAnchor="end">{percent(xmax, 0)}</text>
      </svg>
      {hover !== null ? (
        <ChartTag x={(px(points[hover].x) / W) * 100} y={(py(points[hover].loss) / H) * 100 - 12} tone={hover === run ? "blue" : "ink"}>
          {percent(points[hover].x, 0)} · {money(points[hover].loss)}{hover === run ? " · this run" : ""}
        </ChartTag>
      ) : null}
    </div>
  );
}
