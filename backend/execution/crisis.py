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

    def trade(self, size: D):
        """(frais, gas, impact, quote_status) d'une vente de `size` USD, ou None sans venue."""
        if self.venue is None:
            return None
        impact = _d(exit_cost(self.venue, float(size), float(self.k)))
        status = "executable" if coverage(self.venue, float(size), float(self.k)) == "quoted" else "proxy"
        return size * _d(self.venue.fee_rate), _d(self.venue.gas_usd), impact, status


def _option(action, fraction, sold, trade, foregone, residual, hold_total):
    fees, gas, impact, status = trade if trade else (D(0), D(0), D(0), None)
    cost = fees + gas + impact
    total = cost + foregone + residual
    return {
        "action": action,
        "fraction": None if fraction is None else str(fraction),
        "sold_usd": usd(sold),
        "fees_usd": usd(fees), "gas_usd": usd(gas), "price_impact_usd": usd(impact),
        "exit_cost_usd": usd(cost),
        "foregone_yield_usd": usd(foregone),
        "residual_loss_usd": usd(residual),
        "total_loss_usd": usd(total),
        "saving_vs_hold_usd": usd(hold_total - total),
        "quote_status": status,
        "_total": total,
    }


def _best(options):
    best = min(options, key=lambda o: o["_total"])   # égalité → la première (garder avant vendre)
    for o in options:
        del o["_total"]
    return {k: best[k] for k in ("action", "fraction", "total_loss_usd", "saving_vs_hold_usd")}


def _early(c: _Context, notes: list) -> dict:
    """Réaction tôt : prix d'avant le choc, liquidité du scénario."""
    hold = c.holding_loss
    options = [_option("hold", None, D(0), None, D(0), hold, hold)]
    p = c.position
    if lending.is_lender(p):
        market = c.snapshot.market(p.position_id)
        reduction = 1 - c.k
        available = None if market is None else lending.withdrawable(p, market, float(reduction))
        if available is None:
            notes.append("Early: no market supply/borrow data, withdrawal size unknown.")
        else:
            available_usd = _d(available) * c.gross_before / _d(p.quantity)
            for x in FRACTIONS:
                if x * c.gross_before <= available_usd:
                    options.append(_option("withdraw", x, x * c.gross_before, (D(0), D(0), D(0), "pool_reserves"),
                                           x * c.carry, (1 - x) * hold, hold))
            notes.append("Early: lender exit is a withdrawal from idle market liquidity; fractions beyond it are "
                         "omitted; withdrawal fees and gas are not in the snapshot (shown as zero).")
        return {"options": options, "best": _best(options)}

    if c.venue is None:
        notes.append(f"Early: no exit venue data for {p.exit_venue_id}; only holding is priced.")
        return {"options": options, "best": _best(options)}

    for x in FRACTIONS:   # sortie au prorata : HF/LTV inchangés, la perte restante suit (1 − x)
        sold = x * c.gross_before
        options.append(_option("sell", x, sold, c.trade(sold), x * c.carry, (1 - x) * hold, hold))

    if c.penalty > 0 and "market" in c.impact.internals:   # désendetter juste assez pour rester sûr après le choc
        oracle_factor = c.impact.internals["oracle_collateral_after"] / c.impact.gross_before
        size = _d(deleverage_needed(c.impact.internals["market"], float(c.gross_before),
                                    c.impact.debt_after, oracle_factor))
        if 0 < size < c.gross_before:
            share = size / c.gross_before
            residual = (1 - share) * (hold - c.penalty)   # plus de pénalité ; la perte de prix suit la garantie gardée
            options.append(_option("deleverage", None, size, c.trade(size), share * c.carry, residual, hold))
    return {"options": options, "best": _best(options)}


def _late(c: _Context, lag_hours: float, notes: list) -> dict:
    """Réaction tard : la perte de prix est subie ; seule la pénalité de liquidation reste évitable."""
    sunk = c.holding_loss - c.penalty
    hold = c.penalty
    options = [_option("hold", None, D(0), None, D(0), hold, hold)]
    p = c.position
    if c.venue is not None and not lending.is_lender(p):
        for x in FRACTIONS:   # vendre au prix déjà tombé ; au prorata, la pénalité restante suit (1 − x)
            sold = x * c.gross_after
            options.append(_option("sell", x, sold, c.trade(sold), x * c.carry, (1 - x) * hold, hold))
        if c.penalty > 0 and "market" in c.impact.internals:
            size = _d(deleverage_needed(c.impact.internals["market"],
                                        c.impact.internals["oracle_collateral_after"], c.impact.debt_after))
            if 0 < size < c.gross_after:
                options.append(_option("deleverage", None, size, c.trade(size),
                                       size / c.gross_after * c.carry, D(0), hold))
            if lag_hours <= 0:
                notes.append("Late: no oracle lag window; deleveraging races liquidators once the oracle has updated.")
    elif lending.is_lender(p):
        notes.append("Late: lender withdrawals after the move are not modelled; losses are treated as already incurred.")
    return {"already_incurred_usd": usd(sunk), "options": options, "best": _best(options)}


def crisis_plan(portfolio: dict, snapshot: dict, scenario_request: dict, risk_result: dict | None = None) -> dict:
    """Plan « crise en cours » : options chiffrées par position, réaction tôt et tard."""
    result = risk_result if risk_result is not None else simulate(portfolio, snapshot, scenario_request)
    p, s, r = (Portfolio.from_contract(portfolio), Snapshot.from_contract(snapshot),
               ScenarioRequest.from_contract(scenario_request))
    if result["scenario_id"] != r.scenario_id or result["request_id"] != r.request_id:
        raise ValueError("risk_result does not belong to this scenario_request")
    outcome = scenarios.get(r.scenario_id)(p, s, r)   # faits internes (marché, oracle) ; jamais publiés tels quels
    impacts = {i.position_id: i for i in outcome.impacts}
    published = {row["position_id"]: row for row in result["positions"]}
    k = D(1) - _d(r.param("exit_liquidity_reduction_pct", 0.0))
    lag_hours = r.param("oracle_lag_hours", 0.0) or 0.0

    rows = []
    for position in p.positions:
        notes = []
        c = _Context(position, impacts[position.position_id], published[position.position_id], s, r, k)
        rows.append({
            "position_id": position.position_id,
            "position_type": position.position_type,
            "holding_loss_usd": usd(c.holding_loss),
            "early": _early(c, notes),
            "late": _late(c, lag_hours, notes),
            "warnings": notes,
        })

    warnings = ["Scenario assumed certain: no probability is used. Totals = exit cost + foregone yield + loss still "
                "suffered on what is kept."]
    if k == 1:
        warnings.append("This scenario does not reduce exit liquidity: exits are priced at normal depth.")
    return {
        "simulation_id": result["simulation_id"],
        "portfolio_id": result["portfolio_id"],
        "scenario_id": r.scenario_id,
        "horizon_days": r.horizon_days,
        "depth_factor": str(k),
        "positions": rows,
        "warnings": warnings,
    }
