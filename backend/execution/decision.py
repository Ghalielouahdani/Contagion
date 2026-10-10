"""backend/execution/decision.py — P3 : moteur de décision STAY / REDUCE / EXIT.

Entrées : une position (portfolio.json), le snapshot (market_snapshot.json),
la perte conditionnelle de la position (risk_result.json), l'horizon et
éventuellement une probabilité de scénario.
Sortie : un dict au format decision_result.json (section 11.8).
"""
from decimal import Decimal as D, ROUND_HALF_UP

FRACTIONS = [D("0.00"), D("0.25"), D("0.50"), D("0.75"), D("1.00")]


def usd(x):   # arrondi 2 décimales, seulement à la sortie
    return str(x.quantize(D("0.01"), rounding=ROUND_HALF_UP))


def ratio(x):  # arrondi 4 décimales
    return str(x.quantize(D("0.0001"), rounding=ROUND_HALF_UP))


def price_impact(size, depth):
    """Proxy produit constant : size² / (depth + size)."""
    if size == 0:
        return D(0)
    return size * size / (depth + size)


def annual_carry(position, yields):
    """Rendement net annuel en $ : garantie/token × APY − dette × APY d'emprunt."""
    gross = D(position["gross_value_usd"])
    debt = D(position["debt_value_usd"])
    if position["position_type"] == "collateralized_borrow":
        return gross * D(yields["collateral_supply_apy"]) - debt * D(yields["debt_borrow_apy"])
    return gross * D(yields["token_apy"])


def decide(position, snapshot, conditional_loss_usd, horizon_days, probability=None):
    pid = position["position_id"]
    venue = snapshot["exit_venues"][position["exit_venue_id"]]
    depth = D(venue["effective_depth_usd"])          # profondeur AVANT la crise
    fee_rate = D(venue["fee_rate"])
    gas = D(venue["gas_usd"])
    quote_status = venue["quote_method"]             # executable_quote / pool_reserves / proxy

    gross = D(position["gross_value_usd"])           # on vend x × la garantie (ou le token)
    loss0 = D(conditional_loss_usd)
    carry_h = annual_carry(position, snapshot["yields"][pid]) * D(horizon_days) / D(365)
    p = D(probability) if probability is not None else None

    options = []
    for x in FRACTIONS:
        size = x * gross
        fees = size * fee_rate
        g = gas if x > 0 else D(0)
        impact = price_impact(size, depth)
        cost = fees + g + impact
        residual = (1 - x) * loss0
        foregone = x * carry_h
        avoided = loss0 - residual
        p_star = (cost + foregone) / avoided if avoided > 0 else None
        objective = cost + p * residual + foregone if p is not None else None
        options.append({
            "exit_fraction": str(x),
            "fees_usd": usd(fees) if x > 0 else "0",
            "gas_usd": usd(g) if x > 0 else "0",
            "price_impact_usd": usd(impact) if x > 0 else "0",
            "estimated_exit_cost_usd": usd(cost) if x > 0 else "0",
            "foregone_yield_usd": usd(foregone) if x > 0 else "0",
            "residual_stress_loss_usd": usd(residual) if residual > 0 else "0",
            "break_even_probability": ratio(p_star) if p_star is not None else None,
            "objective_usd": usd(objective) if objective is not None else None,
            "quote_status": quote_status,
            "_objective": objective,   # interne, retiré plus bas
        })

    warnings = []
    if quote_status == "proxy":
        warnings.append("Exit costs use the constant-product proxy on assumed depth; replace with executable quotes.")

    if p is None:
        mode, rec, rec_x = "conditional_stress", "INSUFFICIENT_DATA", None
        best_partial = options[1]
        reason = (f"No scenario probability supplied. Reducing by 25% beats staying if the user's "
                  f"probability of this scenario exceeds {D(best_partial['break_even_probability']) * 100:.2f}%.")
    else:
        mode = "expected_cost"
        best = min(options, key=lambda o: o["_objective"])
        bx = D(best["exit_fraction"])
        rec = "STAY" if bx == 0 else "EXIT" if bx == 1 else "REDUCE"
        rec_x = best["exit_fraction"]
        reason = f"Lowest expected cost at exit fraction {rec_x} with probability {p}."
        if quote_status == "proxy":
            warnings.append("proxy_quotes: recommendation relies on proxy exit costs.")

    for o in options:
        del o["_objective"]

    return {
        "schema_version": "1.0",
        "position_id": pid,
        "horizon_days": horizon_days,
        "mode": mode,
        "currency": "USD",
        "exit_options": options,
        "recommendation": rec,
        "recommended_exit_fraction": rec_x,
        "reason": reason,
        "warnings": warnings,
    }


if __name__ == "__main__":
    # Test sur les valeurs attendues de la section 11.8 (aave_01, depeg)
    position = {"position_id": "aave_01", "position_type": "collateralized_borrow",
                "gross_value_usd": "3000000.00", "debt_value_usd": "1800000.00",
                "exit_venue_id": "venue:usde_usdc"}
    snapshot = {
        "yields": {"aave_01": {"collateral_supply_apy": "0.05", "debt_borrow_apy": "0.055"}},
        "exit_venues": {"venue:usde_usdc": {"quote_method": "proxy", "effective_depth_usd": "300000000",
                                            "fee_rate": "0.001", "gas_usd": "40"}},
    }
    expected = [  # (coût, rendement perdu, p*)
        ("0", "0", None),
        ("2660.32", "244.52", "0.0775"),
        ("9002.69", "489.04", "0.1266"),
        ("19039.38", "733.56", "0.1758"),
        ("32742.97", "978.08", "0.2248"),
    ]
    out = decide(position, snapshot, "150000.00", 7)
    for o, (c, f, p) in zip(out["exit_options"], expected):
        got = (o["estimated_exit_cost_usd"], o["foregone_yield_usd"], o["break_even_probability"])
        print(o["exit_fraction"], got, "OK" if got == (c, f, p) else f"ATTENDU {(c, f, p)}")
    print(out["recommendation"], "|", out["reason"])
    for prob in ["0.05", "0.15", "0.40"]:
        r = decide(position, snapshot, "150000.00", 7, prob)
        print(f"p={prob} ->", r["recommendation"], r["recommended_exit_fraction"])
