/**
 * Dependency graph layout and motion.
 *
 * Layout (both graphs): fixed-size nodes in columns, every edge drawn left to right, rows ordered to
 * reduce crossings (barycentre sweeps), columns centred vertically so equal rows share one axis.
 * - full graph: a node's column is its dependency depth (longest path from the positions); protocols,
 *   off-chain entities and chains sit in the last columns;
 * - scenario graph: a node's column is its distance from the scenario factor (the shock travels right).
 *
 * Motion (scenario graph): the shock reaches one column every STEP seconds. Each node pops in, then its
 * outgoing edges draw themselves towards the next column, their label fades in, and the dashes start
 * flowing. Timings are carried by CSS variables / edge data so a replay is just a remount.
 */
import { motion } from "framer-motion";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "reactflow";
import { EASE } from "./motion/primitives";

export const NODE_W = 210;
export const NODE_H = 84;
const GAP_X = 150;
const GAP_Y = 26;
export const COL_W = NODE_W + GAP_X;
const ROW_H = NODE_H + GAP_Y;
export const STEP = 0.65; // seconds between two columns of the shock
const TERMINAL = new Set(["protocol", "offchain_entity", "chain"]);

type Pos = Record<string, { x: number; y: number }>;
type Link = { source: string; target: string };

/** Barycentre sweeps: order each column by the mean row of its neighbours in the previous / next column. */
function orderColumns(columns: string[][], links: Link[]): string[][] {
  const neighbours = new Map<string, string[]>();
  for (const { source, target } of links) {
    neighbours.set(source, [...(neighbours.get(source) ?? []), target]);
    neighbours.set(target, [...(neighbours.get(target) ?? []), source]);
  }
  const cols = columns.map((c) => [...c]);
  const rowOf = () => new Map(cols.flatMap((c) => c.map((id, i) => [id, i / Math.max(c.length - 1, 1)] as const)));
  const sweep = (from: number, to: number, step: number) => {
    for (let c = from; c !== to; c += step) {
      const ref = new Set(cols[c - step]);
      const rows = rowOf();
      const score = (id: string, i: number) => {
        const near = (neighbours.get(id) ?? []).filter((n) => ref.has(n)).map((n) => rows.get(n)!);
        return near.length ? near.reduce((a, b) => a + b, 0) / near.length : i / Math.max(cols[c].length - 1, 1);
      };
      cols[c] = cols[c].map((id, i) => [id, score(id, i)] as const).sort((a, b) => a[1] - b[1]).map(([id]) => id);
    }
  };
  for (let pass = 0; pass < 4; pass++) {
    sweep(1, cols.length, 1);
    sweep(cols.length - 2, -1, -1);
  }
  return cols;
}

function place(columns: string[][]): Pos {
  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const positions: Pos = {};
  columns.forEach((ids, col) => ids.forEach((id, row) => {
    positions[id] = { x: col * COL_W, y: ((tallest - ids.length) / 2 + row) * ROW_H };
  }));
  return positions;
}

/** Full graph: columns by dependency depth (every edge left to right), terminal types last. */
export function layeredLayout(nodes: Array<{ id: string; type: string }>, links: Link[]): Pos {
  const type = new Map(nodes.map((n) => [n.id, n.type]));
  const layer = new Map(nodes.map((n) => [n.id, 0]));
  const relax = (keep: (l: Link) => boolean) => {
    for (let i = 0; i < nodes.length; i++) {
      let changed = false;
      for (const l of links) {
        if (!keep(l) || !layer.has(l.source) || !layer.has(l.target)) continue;
        if (layer.get(l.target)! < layer.get(l.source)! + 1) { layer.set(l.target, layer.get(l.source)! + 1); changed = true; }
      }
      if (!changed) return; // a cycle would keep changing: the loop bound stops it
    }
  };
  relax((l) => !TERMINAL.has(type.get(l.source) ?? "") && !TERMINAL.has(type.get(l.target) ?? ""));
  const last = 1 + Math.max(0, ...nodes.filter((n) => !TERMINAL.has(n.type)).map((n) => layer.get(n.id)!));
  for (const n of nodes) if (TERMINAL.has(n.type)) layer.set(n.id, last);
  relax((l) => TERMINAL.has(type.get(l.source) ?? "") && TERMINAL.has(type.get(l.target) ?? ""));
  const columns: string[][] = [];
  for (const n of nodes) (columns[layer.get(n.id)!] ??= []).push(n.id);
  return place(orderColumns(columns.filter(Boolean), links));
}

/** Scenario graph: columns given by distance from the scenario factor. */
export function columnLayout(columnOf: Map<string, number>, order: Map<string, number>, links: Link[]): Pos {
  const columns: string[][] = [];
  [...columnOf.entries()].sort((a, b) => (order.get(a[0]) ?? 0) - (order.get(b[0]) ?? 0) || a[0].localeCompare(b[0]))
    .forEach(([id, col]) => (columns[col] ??= []).push(id));
  return place(orderColumns(columns.map((c) => c ?? []), links));
}

export const columnOfX = (x = 0) => Math.max(Math.round(x / COL_W), 0);

/** Scenario edge: draws itself towards the next column, then its label appears and the shock flows. */
export function ShockEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, label, markerEnd, data }: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const delay = (data as { delay?: number } | undefined)?.delay ?? 0;
  const draw = STEP - 0.3;
  return (
    <>
      <path d={path} className="shock-track" />
      <motion.path d={path} className="react-flow__edge-path shock-draw" initial={{ pathLength: 0, opacity: 1 }}
        animate={{ pathLength: 1, opacity: [1, 1, 0] }}
        transition={{ pathLength: { duration: draw, ease: EASE, delay }, opacity: { duration: draw + 0.5, times: [0, 0.75, 1], delay } }} />
      <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={18}
        style={{ animationDelay: `${delay + draw}s` }} />
      {label ? (
        <EdgeLabelRenderer>
          <div className="shock-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, animationDelay: `${delay + draw * 0.6}s` }}>
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export const edgeTypes = { shock: ShockEdge };
