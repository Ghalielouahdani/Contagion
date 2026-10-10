"""Backtest the risk engine against what USDe, sUSDe and PT-sUSDe actually did (Feb 2024 - Oct 2026).

    python -m backend.risk.backtest.run            # prints the report; --json for the raw numbers

A stress engine is never "right" about a scenario that has not happened, but its building blocks
can be checked against history, and the one real USDe stress (Oct 10, 2025) can be replayed:

1. PT pricing: the engine's formula PT = USDe / (1 + implied APY)^(days / 365), fed with Pendle's
   own implied APY, against the PT's observed price.
2. Factor assumptions: does sUSDe move 1:1 with USDe (susde_market_beta = 1)? Does PT stay put
   when USDe holds (pt_implied_apy_shock = 0)?
3. Stress coverage: the largest moves in history (on-chain, CEX, oracle) next to the presets.
4. Portfolio replay: hold the verified portfolio fixed, revalue it with real prices every day,
   and compare with the engine's loss for the same day's USDe move (the way the stress test is used).
5. Oracle vs market on the two stress days in the data (Bybit hack, Oct 10, 2025 CEX crash).
6. Oct 10, 2025 replay: Binance printed 0.65, on-chain pools and the Chainlink feed barely moved.
   Run the engine with each source's shock and compare its liquidation verdicts with the oracle.

Data: backend/risk/backtest/data/history.json.gz (see fetch.py). Hourly on-chain prices from
DefiLlama are sparse for sUSDe and PTs: every check uses paired observations only.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from backend.risk import scenarios
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot
from backend.risk.pricing import SUSDE_RATE_KEY

DATA = Path(__file__).parent / "data" / "history.json.gz"
FIXTURE = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "verified_2026_10_10"
HOUR, DAY = 3600, 86400
CRASH = int(datetime(2025, 10, 10, 21, tzinfo=timezone.utc).timestamp())  # Binance hour of the 0.65 print


@dataclass
class History:
    usde: dict[int, float]
    susde: dict[int, float]
    pts: list[dict]  # {"expiry", "price": {t: p}, "apy": {t: apy}}
    binance: dict[int, list[float]]  # t -> open, high, low, close
    chainlink: list[tuple[int, float]]  # (updatedAt, answer)


def load(path: Path = DATA) -> History:
    with gzip.open(path, "rt") as f:
        raw = json.load(f)
    ints = lambda d: {int(k): v for k, v in d.items()}  # noqa: E731
    pts = [{"expiry": m["expiry"], "price": ints(m["price"]), "apy": ints(m["implied_apy"])} for m in raw["pt"].values()]
    return History(ints(raw["usde"]), ints(raw["susde"]), sorted(pts, key=lambda m: m["expiry"]),
                   ints(raw["binance_usde_ohlc"]), [tuple(r) for r in raw.get("chainlink_usde_usd", [])])


def _q(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    i = q * (len(s) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _near(series: dict[int, float], t: int, tolerance: int = 0):
    for dt in range(0, tolerance + 1, HOUR):
        for c in (t - dt, t + dt):
            if c in series:
                return series[c]
    return None


def _days(expiry: int, t: int) -> float:
    return (expiry - t) / DAY


# 1. PT pricing ---------------------------------------------------------------------------------
def pt_pricing(h: History, min_days: float = 3.0) -> dict:
    """Engine PT formula vs observed price, fed with Pendle's implied APY at the same hour."""
    errors, worst = [], None
    for m in h.pts:
        for t, price in m["price"].items():
            apy, usde = m["apy"].get(t), h.usde.get(t)
            days = _days(m["expiry"], t)
            if apy is None or usde is None or days < min_days or price <= 0:
                continue
            model = usde / (1 + apy) ** (days / 365)
            err = model / price - 1
            errors.append(err)
            if worst is None or abs(err) > abs(worst["error"]):
                worst = {"t": t, "expiry": m["expiry"], "error": err, "observed": price, "model": model}
    absolute = [abs(e) for e in errors]
    return {"observations": len(errors), "median_abs_bps": _q(absolute, 0.5) * 1e4, "p95_abs_bps": _q(absolute, 0.95) * 1e4,
            "p99_abs_bps": _q(absolute, 0.99) * 1e4, "mean_bps": sum(errors) / len(errors) * 1e4 if errors else None,
            "worst": worst}


# 2. Factor assumptions -------------------------------------------------------------------------
def susde_beta(h: History, horizon: int = DAY, stress: float = 0.005) -> dict:
    """sUSDe vs USDe moves over `horizon`: OLS beta (all pairs) and what sUSDe did when USDe moved > stress."""
    xs, ys, events = [], [], []
    for t, s0 in h.susde.items():
        s1, u0, u1 = h.susde.get(t + horizon), h.usde.get(t), h.usde.get(t + horizon)
        if None in (s1, u0, u1):
            continue
        x, y = u1 / u0 - 1, s1 / s0 - 1
        xs.append(x)
        ys.append(y)
        if abs(x) >= stress:
            events.append({"t": t, "usde_move": x, "susde_move": y})
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else float("nan")
    # In stress, the ratio is what a scenario needs; its median is robust to a single bad print (Oct 10, 2025:
    # DefiLlama shows sUSDe +1.4% in the hour USDe printed -2.8%).
    down = [e["susde_move"] / e["usde_move"] for e in events if e["usde_move"] < 0]
    return {"pairs": n, "horizon_hours": horizon // HOUR, "beta": beta, "stress_events": events,
            "stress_down_median_ratio": _q(down, 0.5) if down else None, "stress_down_events": len(down)}


def pt_apy_shocks(h: History, horizon: int = DAY, min_days: float = 14.0) -> dict:
    """Largest implied-APY jumps over `horizon` (what pt_implied_apy_shock would have needed to be)."""
    jumps = []
    for m in h.pts:
        for t, a0 in m["apy"].items():
            a1 = m["apy"].get(t + horizon)
            if a1 is None or _days(m["expiry"], t) < min_days:
                continue
            jumps.append((a1 - a0, t, m["expiry"]))
    jumps.sort(reverse=True)
    return {"pairs": len(jumps), "p99_jump": _q([j[0] for j in jumps], 0.99), "max_jump": jumps[0][0] if jumps else None,
            "max_at": jumps[0][1] if jumps else None}


# 3. Stress coverage ----------------------------------------------------------------------------
def worst_moves(h: History) -> dict:
    def worst(series: dict[int, float], horizon: int):
        best = (0.0, None)
        for t, p0 in series.items():
            p1 = series.get(t + horizon)
            if p1 is not None and p1 / p0 - 1 < best[0]:
                best = (p1 / p0 - 1, t)
        return {"move": best[0], "t": best[1]}

    low = min(h.binance.items(), key=lambda kv: kv[1][2])
    oracle = min(h.chainlink, key=lambda r: r[1]) if h.chainlink else None
    pt_hourly = min((worst(m["price"], HOUR) for m in h.pts), key=lambda r: r["move"])
    return {
        "usde_onchain_1h": worst(h.usde, HOUR), "usde_onchain_24h": worst(h.usde, DAY),
        "usde_onchain_7d": worst(h.usde, 7 * DAY),
        "usde_onchain_min": min(h.usde.values()),
        "susde_onchain_24h": worst(h.susde, DAY),
        "pt_onchain_1h": pt_hourly,
        "usde_binance_low": {"price": low[1][2], "t": low[0], "close": low[1][3]},
        "usde_chainlink_min": None if oracle is None else {"price": oracle[1], "t": oracle[0]},
    }


# 4. Portfolio replay ---------------------------------------------------------------------------
def _fixture():
    load_json = lambda name: json.loads((FIXTURE / f"{name}.json").read_text())  # noqa: E731
    return (Portfolio.from_contract(load_json("portfolio")), Snapshot.from_contract(load_json("market_snapshot")),
            ScenarioRequest.from_contract(load_json("scenario_request")))


def _front_pt(h: History, t: int, min_days: float = 30.0):
    live = [m for m in h.pts if _days(m["expiry"], t) >= min_days and t in m["price"] and t in m["apy"]]
    return min(live, key=lambda m: m["expiry"]) if live else None


def _snapshot_at(snapshot: Snapshot, usde: float, susde: float, pt_apy: float, pt_days: float) -> Snapshot:
    markets = {**snapshot.markets, "pendle_01": {**snapshot.markets["pendle_01"], "pt_implied_apy": str(pt_apy),
                                                  "days_to_maturity": str(pt_days)}}
    return replace(snapshot, prices_usd={**snapshot.prices_usd, "USDe": usde},
                   exchange_rates={**snapshot.exchange_rates, SUSDE_RATE_KEY: susde / usde}, markets=markets)


def engine_loss(portfolio: Portfolio, snapshot: Snapshot, request: ScenarioRequest, **params) -> float:
    neutral = {"usde_spot_shock_pct": 0.0, "susde_market_beta": 1.0, "backing_impairment_pct": 0.0,
               "susde_rate_cut_pct": 0.0, "pt_implied_apy_shock": 0.0, "oracle_lag_hours": 0.0,
               "oracle_pass_through_override": None}
    run = replace(request, scenario_id="usde_depeg", parameters={**neutral, **params})
    outcome = scenarios.get("usde_depeg")(portfolio, snapshot, run)
    return sum(sum(i.loss_components.values()) for i in outcome.impacts)


def portfolio_replay(h: History, horizon: int = DAY) -> dict:
    """Realised daily loss of the verified portfolio (real prices) vs the engine's loss for the day's USDe move."""
    portfolio, snapshot, request = _fixture()
    q = {p.position_id: p for p in portfolio.positions}
    susde_qty = q["ethena_susde_01"].quantity + q["morpho_01"].collateral_quantity
    usde_qty, pt_qty = q["aave_01"].collateral_quantity, q["pendle_01"].quantity
    nav = sum(p.net_equity_usd for p in portfolio.positions)
    rows = []
    for t in sorted(h.usde):
        if t % DAY:
            continue
        u0, u1 = h.usde.get(t), h.usde.get(t + horizon)
        s0, s1 = _near(h.susde, t, 2 * HOUR), _near(h.susde, t + horizon, 2 * HOUR)
        pt = _front_pt(h, t)
        if None in (u0, u1, s0, s1) or pt is None or (t + horizon) not in pt["price"]:
            continue
        p0, p1 = pt["price"][t], pt["price"][t + horizon]
        realised = -(susde_qty * (s1 - s0) + usde_qty * (u1 - u0) + pt_qty * (p1 - p0))
        snap = _snapshot_at(snapshot, u0, s0, pt["apy"][t], _days(pt["expiry"], t))
        predicted = engine_loss(portfolio, snap, request, usde_spot_shock_pct=u1 / u0 - 1)
        rows.append({"t": t, "usde_move": u1 / u0 - 1, "realised": realised, "predicted": predicted})
    errors = [r["realised"] - r["predicted"] for r in rows]
    worst = sorted(rows, key=lambda r: r["realised"], reverse=True)[:5]
    n = len(rows)
    tol = 0.0005 * nav  # 5 bp of NAV: below that, a day's P&L is carry and price noise
    under = [r for r in rows if r["realised"] - r["predicted"] > tol]
    mr, mp = (sum(r["realised"] for r in rows) / n, sum(r["predicted"] for r in rows) / n) if n else (0, 0)
    cov = sum((r["realised"] - mr) * (r["predicted"] - mp) for r in rows)
    sr = math.sqrt(sum((r["realised"] - mr) ** 2 for r in rows))
    sp = math.sqrt(sum((r["predicted"] - mp) ** 2 for r in rows))
    return {"days": n, "nav": nav, "correlation": cov / (sr * sp) if sr and sp else float("nan"),
            "mean_error_usd": sum(errors) / n if n else None,
            "mae_usd": sum(abs(e) for e in errors) / n if n else None,
            "p95_abs_error_usd": _q([abs(e) for e in errors], 0.95),
            "underpredicted_days": len(under), "tolerance_usd": tol, "worst_days": worst}


# 5. Oct 10, 2025 replay ------------------------------------------------------------------------
def crash_replay(h: History) -> dict:
    portfolio, snapshot, request = _fixture()
    window = range(CRASH - 6 * HOUR, CRASH + 12 * HOUR, HOUR)
    binance_low = min(h.binance[t][2] for t in window if t in h.binance)
    onchain_low = min(h.usde[t] for t in window if t in h.usde)
    feed = [p for t, p in h.chainlink if CRASH - 6 * HOUR <= t <= CRASH + 12 * HOUR]
    feed_before = next((p for t, p in reversed(h.chainlink) if t < CRASH - 6 * HOUR), 1.0)
    oracle_low = min(feed, default=feed_before)
    pt = _front_pt(h, CRASH - HOUR)
    pt_drop = None
    if pt:
        before = pt["price"].get(CRASH - HOUR)
        low = min((pt["price"][t] for t in window if t in pt["price"]), default=None)
        apy_before, apy_peak = pt["apy"].get(CRASH - HOUR), max((pt["apy"][t] for t in window if t in pt["apy"]), default=None)
        pt_drop = {"expiry": pt["expiry"], "before": before, "low": low, "move": low / before - 1 if before and low else None,
                   "implied_apy_before": apy_before, "implied_apy_peak": apy_peak}

    def verdict(shock: float, morpho_pass_through: float | None = None) -> dict:
        snap = snapshot
        if morpho_pass_through is not None:
            snap = replace(snapshot, markets={**snapshot.markets, "morpho_01": {**snapshot.markets["morpho_01"],
                                                                              "oracle_pass_through": str(morpho_pass_through)}})
        run = replace(request, scenario_id="usde_depeg", parameters={
            "usde_spot_shock_pct": shock, "susde_market_beta": 1.0, "backing_impairment_pct": 0.0,
            "susde_rate_cut_pct": 0.0, "pt_implied_apy_shock": 0.0, "oracle_lag_hours": 0.0,
            "oracle_pass_through_override": None})
        outcome = scenarios.get("usde_depeg")(portfolio, snap, run)
        return {"shock": shock, "loss_usd": sum(sum(i.loss_components.values()) for i in outcome.impacts),
                "liquidatable": sorted(i.position_id for i in outcome.impacts
                                       if i.risk_metric and i.risk_metric["liquidatable"])}

    binance_shock = binance_low - 1
    oracle_shock = oracle_low / feed_before - 1
    return {
        "binance_low": binance_low, "onchain_low": onchain_low, "chainlink_low": oracle_low,
        "chainlink_before": feed_before, "pt": pt_drop,
        # Engine as configured (Morpho oracle pass-through 1 = follows "the market"), fed the CEX print.
        "engine_binance_shock": verdict(binance_shock),
        # The feed's actual response relative to the CEX move: the pass-through that reproduces the oracle.
        "observed_pass_through": oracle_shock / binance_shock if binance_shock else None,
        "engine_binance_shock_observed_oracle": verdict(binance_shock, oracle_shock / binance_shock),
        "engine_onchain_shock": verdict(onchain_low - 1),
    }


EPISODES = {  # the two USDe stress days in the data: (label, start of the window)
    "bybit_hack_2025_02_21": datetime(2025, 2, 21, tzinfo=timezone.utc),
    "cex_crash_2025_10_10": datetime(2025, 10, 10, 12, tzinfo=timezone.utc),
}


def oracle_vs_market(h: History, span: int = DAY) -> list[dict]:
    """Per episode: lowest USDe price by source. The oracle is what liquidates; the market is what marks."""
    rows = []
    for name, start in EPISODES.items():
        t0 = int(start.timestamp())
        window = range(t0, t0 + span, HOUR)
        onchain = [h.usde[t] for t in window if t in h.usde]
        cex = [h.binance[t][2] for t in window if t in h.binance]
        feed = [p for t, p in h.chainlink if t0 <= t < t0 + span]
        rows.append({"episode": name, "onchain_hourly_low": min(onchain, default=None),
                     "binance_low": min(cex, default=None), "chainlink_low": min(feed, default=None)})
    return rows


def run_all(h: History | None = None) -> dict:
    h = h or load()
    return {"pt_pricing": pt_pricing(h), "susde_beta_1d": susde_beta(h), "susde_beta_1h": susde_beta(h, HOUR),
            "pt_apy_shocks": pt_apy_shocks(h), "worst_moves": worst_moves(h), "portfolio_replay": portfolio_replay(h),
            "oracle_vs_market": oracle_vs_market(h), "crash_replay": crash_replay(h)}


def _ts(t: int | None) -> str:
    return "n/a" if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:00")


def report(r: dict) -> str:
    p, w, rep, c = r["pt_pricing"], r["worst_moves"], r["portfolio_replay"], r["crash_replay"]
    b1, bd, apy = r["susde_beta_1h"], r["susde_beta_1d"], r["pt_apy_shocks"]
    lines = [
        "1. PT pricing formula vs observed PT-sUSDe prices",
        f"   {p['observations']} hourly obs: median |error| {p['median_abs_bps']:.1f} bp, p95 {p['p95_abs_bps']:.1f} bp, "
        f"p99 {p['p99_abs_bps']:.1f} bp, mean {p['mean_bps']:+.1f} bp",
        "2. Factor assumptions",
        f"   sUSDe beta to USDe: {bd['beta']:.2f} (24h, {bd['pairs']} pairs), {b1['beta']:.2f} (1h, {b1['pairs']} pairs); "
        f"engine default 1.0",
        f"   on {bd['stress_down_events']} days USDe fell >= 0.5%, sUSDe fell a median {bd['stress_down_median_ratio']:.2f}x "
        "as much (the low all-days beta is price noise, not decoupling)",
    ]
    lines += [
        f"   PT implied APY 24h jump: p99 {apy['p99_jump']:+.2%}, max {apy['max_jump']:+.2%} ({_ts(apy['max_at'])}); "
        "engine default pt_implied_apy_shock 0",
        "3. Worst moves in history",
        f"   USDe on-chain: 1h {w['usde_onchain_1h']['move']:+.2%} ({_ts(w['usde_onchain_1h']['t'])}), "
        f"24h {w['usde_onchain_24h']['move']:+.2%}, 7d {w['usde_onchain_7d']['move']:+.2%}, min price {w['usde_onchain_min']:.4f}",
        f"   USDe Binance low {w['usde_binance_low']['price']:.4f} ({_ts(w['usde_binance_low']['t'])}, closed the hour at "
        f"{w['usde_binance_low']['close']:.4f})",
        f"   Chainlink USDe/USD min {w['usde_chainlink_min']['price']:.5f} ({_ts(w['usde_chainlink_min']['t'])})"
        if w["usde_chainlink_min"] else "   Chainlink: no data",
        f"   sUSDe on-chain 24h {w['susde_onchain_24h']['move']:+.2%}; PT on-chain 1h {w['pt_onchain_1h']['move']:+.2%} "
        f"({_ts(w['pt_onchain_1h']['t'])})",
        "4. Portfolio replay (verified portfolio, daily)",
        f"   {rep['days']} days, NAV {rep['nav']:,.0f}: correlation realised/predicted {rep['correlation']:.2f}, "
        f"MAE {rep['mae_usd']:,.0f} USD, p95 |error| {rep['p95_abs_error_usd']:,.0f} USD, "
        f"mean (realised - engine) {rep['mean_error_usd']:+,.0f} USD",
        f"   days the engine under-predicted the loss by > {rep['tolerance_usd']:,.0f} USD: {rep['underpredicted_days']}",
    ]
    lines.append("   worst realised days:")
    for d in rep["worst_days"]:
        lines.append(f"     {_ts(d['t'])}: USDe {d['usde_move']:+.2%}, realised loss {d['realised']:,.0f}, "
                     f"engine {d['predicted']:,.0f}")
    lines.append("5. Oracle vs market, lowest USDe price per source")
    fmt = lambda v: "n/a" if v is None else f"{v:.4f}"  # noqa: E731
    for e in r["oracle_vs_market"]:
        lines.append(f"   {e['episode']}: on-chain hourly {fmt(e['onchain_hourly_low'])}, Binance {fmt(e['binance_low'])}, "
                     f"Chainlink {fmt(e['chainlink_low'])}")
    lines += [
        "6. Oct 10, 2025 replay",
        f"   lows: Binance {c['binance_low']:.4f}, on-chain {c['onchain_low']:.4f}, Chainlink {c['chainlink_low']:.5f} "
        f"(from {c['chainlink_before']:.5f})",
    ]
    if c["pt"]:
        lines.append(f"   PT {_ts(c['pt']['expiry'])[:10]}: {c['pt']['before']:.4f} -> {c['pt']['low']:.4f} ({c['pt']['move']:+.2%}); "
                     f"implied APY {c['pt']['implied_apy_before']:.2%} -> peak {c['pt']['implied_apy_peak']:.2%}")
    for key, label in (("engine_binance_shock", "engine, Binance shock, configured oracles"),
                       ("engine_binance_shock_observed_oracle", "engine, Binance shock, observed Chainlink response"),
                       ("engine_onchain_shock", "engine, on-chain shock")):
        v = c[key]
        lines.append(f"   {label}: shock {v['shock']:+.2%} -> loss {v['loss_usd']:,.0f} USD, liquidatable "
                     f"{v['liquidatable'] or 'none'}")
    lines.append(f"   observed oracle pass-through of the CEX move: {c['observed_pass_through']:.3f}")
    return "\n".join(lines)


if __name__ == "__main__":
    result = run_all()
    print(json.dumps(result, indent=2, default=str) if "--json" in sys.argv else report(result))
