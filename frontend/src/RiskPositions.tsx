/**
 * What a risk officer checks before trusting a stress number:
 * - PositionSheets: each position spelled out (assets, quantities, prices used and their source,
 *   protocol market and its parameters, oracle, distance to liquidation and liquidation price,
 *   carry, exit route), all read from the portfolio, the market snapshot and the engine output;
 * - AssumptionRegister: every input the engine used that is not computed, grouped by provenance,
 *   so it is explicit which numbers are observed, which are assumed and which are scenario choices.
 */
import { useMemo, useState } from "react";
import { compactId, labelize, money, percent } from "./lib/format";
import { Term } from "./Term";
import type { AppData, PortfolioPosition, RiskPosition } from "./lib/types";

type Raw = Record<string, unknown>;
type TraceInput = { name: string; value: string | boolean | null; unit: string; source: string };
type TraceStep = { id: string; inputs: TraceInput[] };

const SOURCE_COPY: Record<string, string> = {
  verified: "verified on-chain",
  observed: "observed",
  derived: "derived",
  assumed: "assumption",
  fictional: "fictional holding",
  user_scenario: "scenario parameter",
  protocol_rule: "protocol rule",
};
const SOURCE_ORDER = ["verified", "observed", "protocol_rule", "assumed", "fictional", "user_scenario"];

const str = (v: unknown) => (v === null || v === undefined ? null : String(v));
const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
const qty = (v: unknown) => (num(v) === null ? "n/a" : (num(v) as number).toLocaleString("en-US", { maximumFractionDigits: 4 }));

function priceOf(snapshot: AppData["marketSnapshot"], symbol: string | undefined) {
  const entry = symbol ? (snapshot.prices_usd[symbol] as Raw | undefined) : undefined;
  return entry ? { value: num(entry.value), source: str(entry.source_type) ?? "assumed" } : null;
}

function Source({ source }: { source: string | null }) {
  return <span className="engine-source" data-source={source ?? "assumed"}>{SOURCE_COPY[source ?? "assumed"] ?? source}</span>;
}

export function PositionSheets({ data }: { data: AppData }) {
  const positions = data.portfolio.positions;
  const [open, setOpen] = useState<string>(positions[0]?.position_id ?? "");
  const nav = Number(data.portfolio.totals.net_equity_usd);
  const snapshot = data.marketSnapshot;
  const asOf = `${snapshot.as_of}${snapshot.block_number ? ` · block ${snapshot.block_number}` : ""}`;

  return (
    <section className="visual-panel">
      <p className="eyebrow">Positions in detail</p>
      <h2>What exactly is held, at which price, on which market</h2>
      <p className="microcopy">
        Quantities from the portfolio ({data.portfolio.as_of}); prices, market parameters, oracles, yields and exit routes from the market snapshot
        ({asOf}). Each value carries its provenance.
      </p>
      <div className="engine-tabs">
        {positions.map((p) => (
          <button key={p.position_id} className="engine-chip" data-selected={open === p.position_id} onClick={() => setOpen(p.position_id)}>
            {compactId(p.position_id)} · {p.protocol}
          </button>
        ))}
      </div>
      {positions.filter((p) => p.position_id === open).map((p) => (
        <PositionSheet key={p.position_id} position={p} data={data} nav={nav}
          risk={data.risk.positions.find((r) => r.position_id === p.position_id)} />
      ))}
    </section>
  );
}

function PositionSheet({ position: p, data, nav, risk }: { position: PortfolioPosition; data: AppData; nav: number; risk?: RiskPosition }) {
  const snapshot = data.marketSnapshot;
  const market = (snapshot.markets[p.position_id] as Raw | undefined) ?? null;
  const yields = (snapshot.yields[p.position_id] as Raw | undefined) ?? null;
  const venue = (snapshot.exit_venues[p.exit_venue_id] as Raw | undefined) ?? null;
  const isBorrow = p.position_type === "collateralized_borrow";
  const isLender = p.position_type === "lending_supply";
  const breaks = ((data.analytics?.breaking_points?.liquidation ?? []) as Array<{ position_id: string; mechanism: string; breaks_at_shock_pct: string | null; immune: boolean }>)
    .filter((b) => b.position_id === p.position_id);

  const legs = isBorrow
    ? [
        { role: "Collateral", asset: str(p.collateral_asset) ?? "?", quantity: p.collateral_quantity, sign: 1 },
        { role: "Debt", asset: str(p.debt_asset) ?? "?", quantity: p.debt_quantity, sign: -1 },
      ]
    : [{ role: isLender ? "Supplied (claim on the market)" : "Holding", asset: str(p.asset_symbol) ?? "?", quantity: p.quantity, sign: 1 }];

  const gross = Number(p.gross_value_usd), debt = Number(p.debt_value_usd), net = Number(p.net_equity_usd);
  const carry = yields
    ? isBorrow
      ? gross * (num(yields.collateral_supply_apy) ?? 0) - debt * (num(yields.debt_borrow_apy) ?? 0)
      : gross * (num(yields.token_apy) ?? 0)
    : null;

  // Liquidation price of the collateral seen by the oracle: today's price x (1 - distance to liquidation).
  const metric = risk?.risk_metric ?? null;
  const collateralPrice = isBorrow ? priceOf(snapshot, str(p.collateral_asset) ?? undefined) : null;
  const liquidationPrice = metric && collateralPrice?.value ? collateralPrice.value * (1 - Number(metric.distance_to_liquidation_before_pct)) : null;
  const quotes = (venue?.quotes as Array<Raw> | undefined) ?? [];
  const largest = quotes.length ? quotes.reduce((a, b) => (Number(b.size_usd) > Number(a.size_usd) ? b : a)) : null;
  const supply = num(market?.total_supply_assets), borrowTotal = num(market?.total_borrow_assets);

  return (
    <div className="engine-sheet">
      <div className="engine-sheet-head">
        <div>
          <h3>{compactId(p.position_id)}</h3>
          <p className="microcopy">{labelize(p.protocol)} · {labelize(p.position_type)} · chain {p.chain_id} · market {str(p.market_id) ?? "n/a"}</p>
        </div>
        <Source source={p.data_origin} />
      </div>

      <h4>Holdings</h4>
      <table className="engine-table compact">
        <thead><tr><th><Term>Leg</Term></th><th><Term>Asset</Term></th><th><Term>Quantity</Term></th><th><Term>Price used</Term></th><th><Term>Price source</Term></th><th><Term>Value</Term></th></tr></thead>
        <tbody>{legs.map((leg) => {
          const price = priceOf(snapshot, leg.asset);
          const value = num(leg.quantity) !== null && price?.value != null ? (num(leg.quantity) as number) * price.value : null;
          return (
            <tr key={leg.role}>
              <td>{leg.role}</td><td>{leg.asset}</td><td>{qty(leg.quantity)} {str(p.quantity_unit) ?? ""}</td>
              <td>{price?.value != null ? `$${price.value.toLocaleString("en-US", { maximumFractionDigits: 6 })}` : "derived (see trace)"}</td>
              <td>{price ? <Source source={price.source} /> : <Source source="derived" />}</td>
              <td>{value === null ? "see trace" : money(leg.sign * value)}</td>
            </tr>
          );
        })}</tbody>
      </table>

      <div className="engine-sheet-grid">
        <dl className="engine-facts">
          <dt><Term>Gross value</Term></dt><dd>{money(gross)}</dd>
          <dt><Term>Debt</Term></dt><dd>{money(debt)}</dd>
          <dt><Term>Net equity</Term></dt><dd>{money(net)} · {nav ? percent(net / nav, 1) : "n/a"} of the portfolio</dd>
          <dt><Term>Carry (annual, today's rates)</Term></dt><dd>{carry === null ? "n/a" : money(carry)} {yields ? <Source source={str(yields.source_type)} /> : null}</dd>
        </dl>

        <dl className="engine-facts">
          <dt><Term>Market</Term></dt><dd>{market ? labelize(String(market.market_kind)) : "none (no lending market)"} {market ? <Source source={market.verified ? "verified" : str(market.source_type)} /> : null}</dd>
          {market?.liquidation_threshold ? <><dt><Term>Liquidation threshold</Term></dt><dd>{percent(market.liquidation_threshold as string, 1)} · bonus {percent(market.liquidation_bonus as string, 1)}</dd></> : null}
          {market?.lltv ? <><dt><Term>LLTV</Term></dt><dd>{percent(market.lltv as string, 1)} · incentive {percent(market.liquidation_incentive as string, 1)}</dd></> : null}
          {market?.oracle_type ? <><dt><Term>Oracle</Term></dt><dd>{labelize(String(market.oracle_type))} · follows {percent(market.oracle_pass_through as string, 0)} of a USDe depeg{market.oracle_address ? ` · ${String(market.oracle_address).slice(0, 10)}…` : ""}</dd></> : null}
          {market?.pt_implied_apy ? <><dt><Term>PT</Term></dt><dd>implied APY {percent(market.pt_implied_apy as string, 2)} · {String(market.days_to_maturity)} days to maturity</dd></> : null}
          {isLender && supply && borrowTotal ? <><dt><Term>Lending market</Term></dt><dd>supply {money(supply)} · borrow {money(borrowTotal)} · utilization {percent(borrowTotal / supply, 1)} · our share {percent(Number(p.quantity) / supply, 2)} · borrowers {String(market?.borrower_distribution_source_type ?? "assumed")}</dd></> : null}
        </dl>

        <dl className="engine-facts">
          <dt><Term>Distance to liquidation now</Term></dt>
          <dd>{metric ? `${labelize(metric.type)} ${Number(metric.before).toFixed(3)} (threshold ${Number(metric.threshold).toFixed(3)}) · the oracle price can fall ${percent(metric.distance_to_liquidation_before_pct, 1)}` : isLender ? "lender: losses start when borrowers' collateral stops covering their debt (see the trace)" : "no liquidation threshold"}</dd>
          {liquidationPrice !== null ? <><dt><Term>Liquidation price (oracle)</Term></dt><dd>{str(p.collateral_asset)} at ${liquidationPrice.toFixed(4)}</dd></> : null}
          {breaks.length ? <><dt><Term>Breaks under</Term></dt><dd>{breaks.map((b) => `${labelize(b.mechanism)}: ${b.immune ? "immune" : b.breaks_at_shock_pct !== null ? percent(b.breaks_at_shock_pct, 1) : "n/a"}`).join(" · ")}</dd></> : null}
          <dt><Term>Exit route</Term></dt>
          <dd>{p.exit_venue_id}{venue ? ` · ${labelize(String(venue.quote_method))}${largest ? ` · largest quote ${money(largest.size_usd as string)} at ${Number(largest.loss_pct).toFixed(2)}% loss` : ` · depth ${money(venue.effective_depth_usd as string)}`}` : isLender ? " · withdrawal from idle market liquidity" : " · no venue data"} {venue ? <Source source={str(venue.source_type)} /> : null}</dd>
        </dl>
      </div>
      {market?.warnings && (market.warnings as string[]).length ? <ul className="engine-notes">{(market.warnings as string[]).map((w) => <li key={w}>{w}</li>)}</ul> : null}
    </div>
  );
}

export function AssumptionRegister({ data }: { data: AppData }) {
  const varied = ((data.analytics as { uncertainty?: { drivers: Array<{ assumption: string; low: string; high: string }> } } | null)?.uncertainty?.drivers ?? []);
  const rows = useMemo(() => {
    const steps: Array<{ owner: string; step: TraceStep }> = [
      ...(((data.risk as unknown as { trace?: TraceStep[] }).trace ?? []).map((step) => ({ owner: "portfolio", step }))),
      ...data.risk.positions.flatMap((p) => (((p as unknown as { trace?: TraceStep[] }).trace ?? []).map((step) => ({ owner: p.position_id, step })))),
    ];
    const byKey = new Map<string, { name: string; value: string; source: string; owners: Set<string> }>();
    for (const { owner, step } of steps) {
      for (const input of step.inputs) {
        if (input.source === "derived") continue;
        const value = input.value === null ? "n/a" : String(input.value);
        const key = `${input.source}|${input.name}|${value}`;
        if (!byKey.has(key)) byKey.set(key, { name: input.name, value, source: input.source, owners: new Set() });
        byKey.get(key)!.owners.add(owner);
      }
    }
    return [...byKey.values()].sort((a, b) => SOURCE_ORDER.indexOf(a.source) - SOURCE_ORDER.indexOf(b.source) || a.name.localeCompare(b.name));
  }, [data.risk]);
  const counts = rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.source]: (acc[r.source] ?? 0) + 1 }), {});

  return (
    <section className="visual-panel">
      <p className="eyebrow">Assumption register</p>
      <h2>Every input this run rests on</h2>
      <p className="microcopy">
        The engine is deterministic: the same inputs always give the same numbers. What differs is how much of the input is observed.
        {" "}{SOURCE_ORDER.filter((s) => counts[s]).map((s) => `${counts[s]} ${SOURCE_COPY[s]}`).join(" · ")}.
        {varied.length ? " Unverified model assumptions are also varied in the uncertainty range (step 2): " + varied.map((v) => v.assumption).join(", ") + "." : ""}
      </p>
      <table className="engine-table compact">
        <thead><tr><th><Term>Input</Term></th><th><Term>Value</Term></th><th><Term>Provenance</Term></th><th><Term>Used by</Term></th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={`${r.source}-${r.name}-${r.value}`}>
            <td>{r.name}</td><td>{r.value}</td><td><Source source={r.source} /></td>
            <td>{[...r.owners].map(compactId).join(", ")}</td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}
