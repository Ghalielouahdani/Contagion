"""backend/execution/crisis.py — P3 : mode « crise en cours » (le scénario est certain).

Question du gérant : « ce scénario arrive ; que faire de chaque position pour perdre le moins ? »
Aucune probabilité : on compare, en dollars, la perte de garder et le coût de vendre.

- Perte de garder = perte du scénario (P2) sans sa composante de vente forcée (execution_haircut) :
  garder ne paie pas de frais de sortie.
- Coût de vendre = frais + gas + impact de prix sur la venue, à la profondeur DU SCÉNARIO
  (k = 1 − exit_liquidity_reduction_pct ; k = 1 si le scénario ne réduit pas la liquidité).

Deux moments de réaction :
- tôt  : on agit au prix d'avant le choc ; on évite la perte de prix, les pénalités, la mauvaise dette ;
- tard : le marché a déjà bougé ; la perte de prix est SUBIE (jamais présentée comme évitable),
         seule la pénalité de liquidation peut encore être évitée.

Au niveau portefeuille, une stratégie = une action par position ; les ventes sur une même venue
sont chiffrées ensemble (vendre deux positions dans la même pool coûte plus que deux ventes séparées).
"""
from __future__ import annotations

from decimal import Decimal as D, ROUND_HALF_UP

import backend.risk  # noqa: F401  (enregistre les sept scénarios)
from backend.risk import lending, scenarios, simulate
from backend.risk.liquidity import coverage, exit_cost
from backend.risk.metrics import deleverage_needed
from backend.risk.model import Portfolio, ScenarioRequest, Snapshot

FRACTIONS = (D("0.25"), D("0.50"), D("0.75"), D("1.00"))
EXIT_ONLY = {"execution_haircut"}   # coût d'une sortie forcée : payé seulement si l'on vend
TIMINGS = ("early", "late")
SELLING = {"sell", "deleverage"}    # actions qui vendent sur la venue de sortie


def _d(x) -> D:
    return D(repr(float(x)))


def usd(x: D) -> str:
    value = x.quantize(D("0.01"), rounding=ROUND_HALF_UP)
    return str(value if value else abs(value))   # jamais "-0.00"


class _Context:
    """Données d'une position dont toutes les options ont besoin."""

    def __init__(self, position, impact, published, snapshot, request, k):
        self.position, self.impact, self.snapshot, self.k = position, impact, snapshot, k
        self.venue = snapshot.venues.get(position.exit_venue_id)
        self.components = {name: _d(v) for name, v in published["loss_components"].items()}
        self.holding_loss = sum(v for name, v in self.components.items() if name not in EXIT_ONLY)
        self.penalty = self.components.get("liquidation_penalty", D(0))
        self.gross_before = _d(published["gross_value_before_usd"])
        self.gross_after = _d(published["gross_value_after_usd"])
        # Carry sur l'horizon ; dans carry_squeeze il est déjà dans la perte (negative_carry) : pas compté deux fois.
        self.carry = D(0) if "negative_carry" in self.components else self._carry(request.horizon_days)

    def _carry(self, horizon_days) -> D:
        y = self.snapshot.yields.get(self.position.position_id, {})
        p = self.position
        if p.is_borrow:
            annual = _d(y.get("collateral_supply_apy", 0.0)) * self.gross_before \
                - _d(y.get("debt_borrow_apy", 0.0)) * _d(p.debt_value_usd)
        else:
            annual = _d(y.get("token_apy", 0.0)) * self.gross_before
        return annual * D(horizon_days) / D(365)


def _price(venue, size: D, k: D) -> tuple[D, D, D, str]:
    """(frais, gas, impact, quote_status) d'une vente de `size` USD sur la venue à la profondeur k."""
    impact = _d(exit_cost(venue, float(size), float(k)))
    status = "executable" if coverage(venue, float(size), float(k)) == "quoted" else "proxy"
    return size * _d(venue.fee_rate), _d(venue.gas_usd), impact, status


def _raw(action, fraction, sold, venue_id, priced, foregone, residual):
    """Option en valeurs exactes ; le formatage n'a lieu qu'à la sortie."""
    fees, gas, impact, status = priced if priced else (D(0), D(0), D(0), None)
    return {"action": action, "fraction": fraction, "sold": sold, "venue_id": venue_id,
            "fees": fees, "gas": gas, "impact": impact, "status": status,
            "foregone": foregone, "residual": residual,
            "total": fees + gas + impact + foregone + residual}


def _fmt(o: dict, hold_total: D) -> dict:
    return {
        "action": o["action"],
        "fraction": None if o["fraction"] is None else str(o["fraction"]),
        "sold_usd": usd(o["sold"]),
        "fees_usd": usd(o["fees"]), "gas_usd": usd(o["gas"]), "price_impact_usd": usd(o["impact"]),
        "exit_cost_usd": usd(o["fees"] + o["gas"] + o["impact"]),
        "foregone_yield_usd": usd(o["foregone"]),
        "residual_loss_usd": usd(o["residual"]),
        "total_loss_usd": usd(o["total"]),
        "saving_vs_hold_usd": usd(hold_total - o["total"]),
        "quote_status": o["status"],
    }


def _key(o: dict) -> tuple:
    return o["action"], None if o["fraction"] is None else str(o["fraction"])


def _early(c: _Context, notes: list) -> list[dict]:
    """Réaction tôt : prix d'avant le choc, liquidité du scénario."""
    hold = c.holding_loss
    options = [_raw("hold", None, D(0), None, None, D(0), hold)]
    p = c.position
    if lending.is_lender(p):
        market = c.snapshot.market(p.position_id)
        available = None if market is None else lending.withdrawable(p, market, float(1 - c.k))
        if available is None:
            notes.append("Early: no market supply/borrow data, withdrawal size unknown.")
            return options
        available_usd = _d(available) * c.gross_before / _d(p.quantity)
        for x in FRACTIONS:
            if x * c.gross_before <= available_usd:
                options.append(_raw("withdraw", x, x * c.gross_before, None, (D(0), D(0), D(0), "pool_reserves"),
                                    x * c.carry, (1 - x) * hold))
        notes.append("Early: lender exit is a withdrawal from idle market liquidity; fractions beyond it are "
                     "omitted; withdrawal fees and gas are not in the snapshot (shown as zero).")
        return options

    if c.venue is None:
        notes.append(f"Early: no exit venue data for {p.exit_venue_id}; only holding is priced.")
        return options

    for x in FRACTIONS:   # sortie au prorata : HF/LTV inchangés, la perte restante suit (1 − x)
        sold = x * c.gross_before
        options.append(_raw("sell", x, sold, p.exit_venue_id, _price(c.venue, sold, c.k), x * c.carry, (1 - x) * hold))

    if c.penalty > 0 and "market" in c.impact.internals:   # désendetter juste assez pour rester sûr après le choc
        oracle_factor = c.impact.internals["oracle_collateral_after"] / c.impact.gross_before
        size = _d(deleverage_needed(c.impact.internals["market"], float(c.gross_before),
                                    c.impact.debt_after, oracle_factor))
        if 0 < size < c.gross_before:
            share = size / c.gross_before
            residual = (1 - share) * (hold - c.penalty)   # plus de pénalité ; la perte de prix suit la garantie gardée
            options.append(_raw("deleverage", None, size, p.exit_venue_id, _price(c.venue, size, c.k),
                                share * c.carry, residual))
    return options


def _late(c: _Context, lag_hours: float, notes: list) -> list[dict]:
    """Réaction tard : la perte de prix est subie ; seule la pénalité de liquidation reste évitable."""
    hold = c.penalty
    options = [_raw("hold", None, D(0), None, None, D(0), hold)]
    p = c.position
    if lending.is_lender(p):
        notes.append("Late: lender withdrawals after the move are not modelled; losses are treated as already incurred.")
        return options
    if c.venue is None:
        return options
    for x in FRACTIONS:   # vendre au prix déjà tombé ; au prorata, la pénalité restante suit (1 − x)
        sold = x * c.gross_after
        options.append(_raw("sell", x, sold, p.exit_venue_id, _price(c.venue, sold, c.k), x * c.carry, (1 - x) * hold))
    if c.penalty > 0 and "market" in c.impact.internals:
        size = _d(deleverage_needed(c.impact.internals["market"],
                                    c.impact.internals["oracle_collateral_after"], c.impact.debt_after))
        if 0 < size < c.gross_after:
            options.append(_raw("deleverage", None, size, p.exit_venue_id, _price(c.venue, size, c.k),
                                size / c.gross_after * c.carry, D(0)))
        if lag_hours <= 0:
            notes.append("Late: no oracle lag window; deleveraging races liquidators once the oracle has updated.")
    return options


class CrisisModel:
    """Toutes les options chiffrées d'un scénario, réutilisables pour évaluer des stratégies de portefeuille."""

    def __init__(self, portfolio: dict, snapshot: dict, scenario_request: dict, risk_result: dict | None = None):
        result = risk_result if risk_result is not None else simulate(portfolio, snapshot, scenario_request)
        p, s, r = (Portfolio.from_contract(portfolio), Snapshot.from_contract(snapshot),
                   ScenarioRequest.from_contract(scenario_request))
        if result["scenario_id"] != r.scenario_id or result["request_id"] != r.request_id:
            raise ValueError("risk_result does not belong to this scenario_request")
        outcome = scenarios.get(r.scenario_id)(p, s, r)   # faits internes (marché, oracle) ; jamais publiés tels quels
        impacts = {i.position_id: i for i in outcome.impacts}
        published = {row["position_id"]: row for row in result["positions"]}

        self.result, self.snapshot, self.request = result, s, r
        self.k = D(1) - _d(r.param("exit_liquidity_reduction_pct", 0.0))
        self.lag_hours = r.param("oracle_lag_hours", 0.0) or 0.0
        self.contexts, self.options, self.notes = {}, {}, {}
        for position in p.positions:
            pid, notes = position.position_id, []
            c = _Context(position, impacts[pid], published[pid], s, r, self.k)
            self.contexts[pid] = c
            self.options[pid] = {"early": _early(c, notes), "late": _late(c, self.lag_hours, notes)}
            self.notes[pid] = notes

    def option(self, position_id: str, timing: str, action: str, fraction=None) -> dict:
        wanted = (action, None if fraction is None else str(D(str(fraction)).quantize(D("0.01"))))
        for o in self.options[position_id][timing]:
            if _key(o) == wanted:
                return o
        raise ValueError(f"No {action} {fraction} option for {position_id} ({timing})")

    def evaluate(self, timing: str, choices: dict, venues: dict | None = None) -> dict:
        """Résultat d'une stratégie (position_id → (action, fraction)) avec vente groupée par venue.

        `venues` remplace la venue de sortie d'une position (ex. une route de couverture cotée à la demande).
        Positions absentes de `choices` : gardées.
        """
        venues = venues or {}
        chosen = {pid: self.option(pid, timing, *choices.get(pid, ("hold", None))) for pid in self.contexts}
        by_venue, standalone = {}, D(0)
        legs = {}
        for pid, o in chosen.items():
            if o["action"] in SELLING:
                venue = venues.get(pid) or self.contexts[pid].venue
                fees, gas, impact, _ = _price(venue, o["sold"], self.k)
                standalone += impact
                legs[pid] = (venue, fees, gas)
                by_venue.setdefault(venue.venue_id, (venue, []))[1].append((pid, o["sold"]))
        joint_impact = {}
        for venue_id, (venue, sales) in by_venue.items():
            total_sold = sum(size for _, size in sales)
            impact = _d(exit_cost(venue, float(total_sold), float(self.k)))
            for pid, size in sales:   # impact groupé réparti au prorata des tailles vendues
                joint_impact[pid] = impact * size / total_sold
        positions, total = [], D(0)
        for pid, o in chosen.items():
            fees, gas = (legs[pid][1], legs[pid][2]) if pid in legs else (o["fees"], o["gas"])
            impact = joint_impact.get(pid, o["impact"])
            line = {**o, "fees": fees, "gas": gas, "impact": impact,
                    "total": fees + gas + impact + o["foregone"] + o["residual"]}
            total += line["total"]
            hold_total = self.options[pid][timing][0]["total"]
            positions.append({"position_id": pid, **_fmt(line, hold_total)})
        hold_all = sum(opts[timing][0]["total"] for opts in self.options.values())
        joint = sum(_d(exit_cost(v, float(sum(sz for _, sz in sales)), float(self.k))) for v, sales in by_venue.values())
        return {
            "timing": timing,
            "positions": positions,
            "total_loss_usd": usd(total),
            "saving_vs_hold_all_usd": usd(hold_all - total),
            "shared_venue_penalty_usd": usd(joint - standalone),
            "_total": total,
        }

    def plan_rows(self) -> list[dict]:
        rows = []
        for pid, c in self.contexts.items():
            row = {"position_id": pid, "position_type": c.position.position_type,
                   "holding_loss_usd": usd(c.holding_loss)}
            for timing in TIMINGS:
                options = self.options[pid][timing]
                hold = options[0]["total"]
                best = min(options, key=lambda o: o["total"])   # égalité → la première (garder avant vendre)
                block = {"options": [_fmt(o, hold) for o in options],
                         "best": {k: v for k, v in _fmt(best, hold).items()
                                  if k in ("action", "fraction", "total_loss_usd", "saving_vs_hold_usd")}}
                if timing == "late":
                    block = {"already_incurred_usd": usd(c.holding_loss - c.penalty), **block}
                row[timing] = block
            row["warnings"] = self.notes[pid]
            rows.append(row)
        return rows

    def meta(self) -> dict:
        warnings = ["Scenario assumed certain: no probability is used. Totals = exit cost + foregone yield + loss "
                    "still suffered on what is kept."]
        if self.k == 1:
            warnings.append("This scenario does not reduce exit liquidity: exits are priced at normal depth.")
        return {"simulation_id": self.result["simulation_id"], "portfolio_id": self.result["portfolio_id"],
                "scenario_id": self.request.scenario_id, "horizon_days": self.request.horizon_days,
                "depth_factor": str(self.k), "warnings": warnings}


def _best_choices(model: CrisisModel, timing: str) -> dict:
    return {pid: _key(min(opts[timing], key=lambda o: o["total"])) for pid, opts in model.options.items()}


def min_loss_choices(model: CrisisModel, timing: str, max_rounds: int = 10) -> dict:
    """Meilleure action par position, puis ajustement coordonné quand des positions partagent une venue."""
    choices = _best_choices(model, timing)
    best = model.evaluate(timing, choices)["_total"]
    for _ in range(max_rounds):
        improved = False
        for pid, opts in model.options.items():
            for o in opts[timing]:
                trial = {**choices, pid: _key(o)}
                total = model.evaluate(timing, trial)["_total"]
                if total < best:
                    choices, best, improved = trial, total, True
        if not improved:
            break
    return choices


def candidate_strategies(model: CrisisModel, timing: str) -> list[dict]:
    """Stratégies de portefeuille calculées par le code (aucune n'est choisie par une IA ici)."""
    pids = list(model.options)

    def available(pid, action, fraction=None):
        try:
            model.option(pid, timing, action, fraction)
            return True
        except ValueError:
            return False

    exit_all = {}
    for pid in pids:
        for action in ("sell", "withdraw"):
            if available(pid, action, "1.00"):
                exit_all[pid] = (action, "1.00")
                break
    protect = {pid: ("deleverage", None) for pid in pids if available(pid, "deleverage")}
    specs = [
        ("hold_all", "Keep every position.", {}),
        ("exit_all", "Exit every position that can be exited (sell or withdraw 100%).", exit_all),
        ("min_loss", "Lowest total loss: best action per position, adjusted for shared exit venues.",
         min_loss_choices(model, timing)),
        ("protect_liquidations", "Keep exposure; only deleverage positions the scenario makes liquidatable.", protect),
    ]
    strategies, seen = [], {}
    for strategy_id, description, choices in specs:
        result = model.evaluate(timing, choices)
        del result["_total"]
        signature = tuple(sorted((pid, c) for pid, c in choices.items() if c != ("hold", None)))
        strategies.append({"strategy_id": strategy_id, "description": description,
                           "choices": {pid: {"action": a, "fraction": f} for pid, (a, f) in choices.items()},
                           "same_as": seen.get(signature),   # même combinaison qu'une stratégie précédente
                           **result})
        seen.setdefault(signature, strategy_id)
    return strategies


def crisis_plan(portfolio: dict, snapshot: dict, scenario_request: dict, risk_result: dict | None = None,
                include_strategies: bool = False, quote_source=None) -> dict:
    """Plan « crise en cours » : options chiffrées par position (tôt / tard), stratégies de portefeuille
    et univers de couverture. `quote_source` (réseau) active les cotations à la demande des couvertures."""
    model = CrisisModel(portfolio, snapshot, scenario_request, risk_result)
    return plan_from_model(model, snapshot, scenario_request, include_strategies, quote_source)


def plan_from_model(model: CrisisModel, snapshot: dict, scenario_request: dict, include_strategies: bool = False,
                    quote_source=None) -> dict:
    from backend.execution.hedging import hedge_universe, rotation_strategies

    plan = {**model.meta(), "positions": model.plan_rows()}
    if include_strategies:
        universe = hedge_universe(snapshot, scenario_request, quote_source)
        plan["strategies"] = {timing: candidate_strategies(model, timing)
                              + rotation_strategies(model, timing, universe, quote_source) for timing in TIMINGS}
        plan["hedging"] = universe
    plan["warnings"] = plan.pop("warnings")
    return plan
