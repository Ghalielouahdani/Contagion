/**
 * Scenario Lab, net equity before / after per position, with motion: the "before" bars rise, then each
 * "after" bar drops from its before height to its stressed value while the loss appears hatched in red.
 * Hover shows the values in a tag; click selects the position (shared with the gauge, breakdown and graph).
 * Values come from the last run's risk_result.
 */
import { motion } from "framer-motion";
import { useId, useState } from "react";
import { money } from "./lib/format";
import { EASE, SPRING } from "./motion/primitives";

export type EquityRow = { id: string; name: string; before: number; after: number };

export function EquityBars({ rows, selected, hovered, onSelect, onHover }: {
  rows: EquityRow[];
  selected: string;
  hovered: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const hatch = useId().replace(/:/g, "");
  const [tag, setTag] = useState<string | null>(null);
  const W = 720, H = 320, left = 70, right = 8, top = 34, bottom = 46;
  const step = niceStep(Math.max(1, ...rows.flatMap((r) => [r.before, r.after])) - Math.min(0, ...rows.flatMap((r) => [r.before, r.after])));
  const hi = Math.ceil(Math.max(1, ...rows.flatMap((r) => [r.before, r.after])) / step) * step;
  const lo = Math.floor(Math.min(0, ...rows.flatMap((r) => [r.before, r.after])) / step) * step;
  const y = (v: number) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const y0 = y(0);
  const rect = (v: number) => (v >= 0 ? { y: y(v), height: y0 - y(v) } : { y: y0, height: y(v) - y0 });
  const band = (W - left - right) / Math.max(rows.length, 1);
  const bw = Math.min(30, band * 0.26);
  const xBefore = (i: number) => left + band * i + band / 2 - bw - 2;
  const xAfter = (i: number) => left + band * i + band / 2 + 2;
  const ticks = Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step);
  const focus = hovered ?? tag;

  return (
    <div className="equity-bars">
      <div className="equity-legend">
        <span><i data-kind="before" /> Before stress</span>
        <span><i data-kind="after" /> After stress</span>
        <span><i data-kind="loss" /> Loss</span>
      </div>
      <div className="story-svg-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} className="story-svg" role="img"
          aria-label={rows.map((r) => `${r.name}: ${money(r.before)} before, ${money(r.after)} after`).join("; ")}>
          <defs>
            <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="2" height="6" className="hatch-ink" />
            </pattern>
          </defs>
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} className={Math.abs(t) < step / 2 ? "axis" : "grid"} />
              <text x={left - 10} y={y(t) + 4} className="label" textAnchor="end">{money(t)}</text>
            </g>
          ))}
          {rows.map((r, i) => {
            const isSelected = r.id === selected;
            const dim = focus !== null && focus !== r.id;
            const loss = r.before - r.after;
            const delayUp = 0.1 + i * 0.06;
            const delayDrop = 0.75 + i * 0.07;
            return (
              <g key={r.id} className="equity-pair" data-dim={dim} data-selected={isSelected}
                onMouseEnter={() => { setTag(r.id); onHover(r.id); }} onMouseLeave={() => { setTag(null); onHover(null); }}
                onClick={() => onSelect(r.id)}>
                <rect x={left + band * i} y={top - 26} width={band} height={H - top - bottom + 26} className="hit" />
                {isSelected ? (
                  <motion.rect x={left + band * i + 4} y={H - bottom + 30} width={band - 8} height={2} className="selection"
                    style={{ transformBox: "fill-box", transformOrigin: "center" }}
                    initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 0.36, ease: EASE }} />
                ) : null}
                <motion.rect x={xBefore(i)} width={bw} className="bar bar-before"
                  initial={{ y: y0, height: 0 }} animate={rect(r.before)} transition={{ ...SPRING, delay: delayUp }} />
                <motion.rect x={xAfter(i)} width={bw} className="bar bar-after"
                  initial={{ y: y0, height: 0 }}
                  animate={{ y: [y0, rect(r.before).y, rect(r.after).y], height: [0, rect(r.before).height, rect(r.after).height] }}
                  transition={{ duration: 1.5, times: [0, 0.4, 1], ease: EASE, delay: delayUp }} />
                {loss > 0.5 ? (
                  <motion.rect x={xAfter(i)} width={bw} fill={`url(#${hatch})`} className="bar-loss-hatch"
                    initial={{ y: y(r.before), height: 0, opacity: 0 }}
                    animate={{ y: y(r.before), height: Math.max(y(r.after) - y(r.before), 0), opacity: 1 }}
                    transition={{ duration: 0.9, ease: EASE, delay: delayDrop }} />
                ) : null}
                <motion.text x={left + band * i + band / 2} y={Math.min(y(r.before), y(r.after)) - 10} textAnchor="middle"
                  className="value" data-tone={loss > 0.5 ? "loss" : loss < -0.5 ? "gain" : "flat"}
                  initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: delayDrop + 0.6 }}>
                  {loss > 0.5 ? `−${money(loss)}` : loss < -0.5 ? `+${money(-loss)}` : "no loss"}
                </motion.text>
                <text x={left + band * i + band / 2} y={H - bottom + 20} textAnchor="middle" className="label equity-name">{r.name}</text>
              </g>
            );
          })}
        </svg>
        {tag ? (() => {
          const i = rows.findIndex((r) => r.id === tag);
          const r = rows[i];
          return (
            <span className="np-tag story-hover-tag" data-tone="ink"
              style={{ left: `${((left + band * i + band / 2) / W) * 100}%`, top: `${((Math.min(y(r.before), y(r.after)) - 30) / H) * 100}%` }}>
              {r.name} · {money(r.before)} → {money(r.after)}
            </span>
          );
        })() : null}
      </div>
    </div>
  );
}

/** Round axis step (1, 2, 2.5 or 5 x 10^k) giving at most five intervals over `span`. */
function niceStep(span: number) {
  const raw = span / 5;
  const power = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 2.5, 5, 10].find((m) => m * power >= raw) ?? 10) * power;
}
