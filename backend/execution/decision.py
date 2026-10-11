"""backend/execution/decision.py — P3 : moteur de décision STAY / REDUCE / EXIT.

Entrées : une position (portfolio.json), le snapshot (market_snapshot.json),
la perte conditionnelle de la position (risk_result.json), l'horizon et
éventuellement une probabilité de scénario.
Sortie : un dict au format decision_result.json (section 11.8).

Point d'entrée : decide_position(portfolio, snapshot, risk_result, scenario_request, position_id).
"""
import json
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

from .exit_cost import DECLARED_METHOD, DEFAULT_ESTIMATOR, PRIORITY

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "demo_ethena_01"
FRACTIONS = [D("0.00"), D("0.25"), D("0.50"), D("0.75"), D("1.00")]
SCENARIO_LABELS = {"usde_depeg": "depeg", "liquidity_crisis": "liquidity crisis"}


def usd(x):   # arrondi 2 décimales, seulement à la sortie
    return str(x.quantize(D("0.01"), rounding=ROUND_HALF_UP))


def ratio(x):  # arrondi 4 décimales
    return str(x.quantize(D("0.0001"), rounding=ROUND_HALF_UP))


def annual_carry(position, yields, asset_yields=None):
    """Rendement net annuel en $ : garantie/token × APY − dette × APY d'emprunt.

    La garantie rapporte aussi son rendement propre (sUSDe via son taux de change), même si le protocole
    de prêt ne verse rien dessus : `asset_yields` du snapshot."""
    gross = D(position["gross_value_usd"])
    debt = D(position["debt_value_usd"])
    if position["position_type"] == "collateralized_borrow":
        intrinsic = D((asset_yields or {}).get(position.get("collateral_asset"), {}).get("value", "0"))
        return gross * (D(yields["collateral_supply_apy"]) + intrinsic) - debt * D(yields["debt_borrow_apy"])
    return gross * D(yields["token_apy"])


def pct(x):  # 0.0775 → "7.75", 0.10 → "10"
    return f"{x * 100:.2f}".rstrip("0").rstrip(".")


def option_label(x):
    return "Exiting fully" if x == 1 else f"Reducing by {int(x * 100)}%"


def decide(position, snapshot, conditional_loss_usd, horizon_days, probability=None, scenario_id=None,
           estimator=DEFAULT_ESTIMATOR):
    pid = position["position_id"]
    venue_id = position["exit_venue_id"]
    venue = snapshot["exit_venues"].get(venue_id)    # profondeur et frais AVANT la crise

    # Ce qu'on vend, au prix d'avant le choc (section 7.2) :
    #  - token / PT : x × quantité × prix = x × valeur brute ;
    #  - avec dette : x × garantie (la dette x × debt est remboursée en USDC, sans impact de prix).
    gross = D(position["gross_value_usd"])
    loss0 = D(conditional_loss_usd)
    carry_h = annual_carry(position, snapshot["yields"][pid], snapshot.get("asset_yields")) * D(horizon_days) / D(365)

    # Une cotation par taille de sortie ; les tailles sans prix sont écartées (jamais de coût inventé).
    quotes = {x: estimator.quote(venue_id, venue, x * gross) for x in FRACTIONS[1:]}
    priced = {x: q for x, q in quotes.items() if q is not None}
    statuses = {q.quote_status for q in priced.values()}
    best_status = min(statuses, key=PRIORITY.index) if statuses else "unavailable"
    if probability is not None and not D(0) <= D(probability) <= D(1):
        raise ValueError(f"probability must be between 0 and 1, got {probability!r}")
    # Sans aucun prix, pas de J(x) : on retombe en conditional_stress (section 8).
    p = D(probability) if probability is not None and priced else None

    def option(x, q):
        cost = q.total_usd if q else D(0)
        residual = (1 - x) * loss0
        foregone = x * carry_h
        avoided = loss0 - residual
        # p* ≤ 0 (sortie qui rapporte plus qu'elle ne coûte) : l'option bat STAY pour toute probabilité.
        p_star = max(D(0), (cost + foregone) / avoided) if avoided > 0 else None
        objective = cost + p * residual + foregone if p is not None else None
        return {
            "exit_fraction": str(x),
            "fees_usd": usd(q.fees_usd) if q else "0",
            "gas_usd": usd(q.gas_usd) if q else "0",
            "price_impact_usd": usd(q.price_impact_usd) if q else "0",
            "estimated_exit_cost_usd": usd(cost) if q else "0",
            "foregone_yield_usd": usd(foregone) if x > 0 else "0",
            "residual_stress_loss_usd": usd(residual) if residual != 0 else "0",
            "break_even_probability": ratio(p_star) if p_star is not None else None,
            "objective_usd": usd(objective) if objective is not None else None,
            # x = 0 : rien à vendre ; on affiche la meilleure méthode utilisée sur cette venue.
            "quote_status": q.quote_status if q else best_status,
            "_objective": objective,   # internes, retirés plus bas
            "_p_star": p_star,
        }

    options = [option(FRACTIONS[0], None)] + [option(x, q) for x, q in priced.items()]

    warnings = []
    if "proxy" in statuses:
        warnings.append("Exit costs use the constant-product proxy on assumed depth; replace with executable quotes.")
    declared = DECLARED_METHOD.get(venue.get("quote_method")) if venue else None
    if declared and statuses and PRIORITY.index(declared) < PRIORITY.index(best_status):
        warnings.append(f"Venue {venue_id} declares quote_method={venue['quote_method']} "
                        f"but no such quote was available; {best_status} used.")
    missing = [str(x) for x in FRACTIONS[1:] if x not in priced]
    if missing:
        warnings.append(f"No exit price on {venue_id} for exit fractions {', '.join(missing)}; rows omitted.")

    # Meilleur seuil de bascule : l'option qui bat STAY au p le plus bas.
    scenario = SCENARIO_LABELS.get(scenario_id, "scenario")
    candidates = [o for o in options if o["_p_star"] is not None]
    cheapest = min(candidates, key=lambda o: o["_p_star"]) if candidates else None
    if cheapest is None:
        threshold = f"No exit reduces the loss under this {scenario}, so no exit can beat staying."
    elif cheapest["_p_star"] > 1:   # p* > 100 % : la sortie coûte plus que toute la perte évitée
        threshold = f"Every exit costs more than the loss it avoids, so no exit can beat staying even if this {scenario} is certain."
    else:
        threshold = (f"{option_label(D(cheapest['exit_fraction']))} beats staying if the user's probability "
                     f"of this {scenario} exceeds {pct(D(cheapest['break_even_probability']))}%.")

    # Règles de la section 8.
    if not priced:
        mode, rec, rec_x = "conditional_stress", "INSUFFICIENT_DATA", None
        reason = f"No exit price available on {venue_id}: exit costs cannot be estimated, no trade is recommended."
    elif p is None:
        mode, rec, rec_x = "conditional_stress", "INSUFFICIENT_DATA", None
        reason = "No scenario probability supplied"
        reason += " and all quotes are proxies. " if statuses == {"proxy"} else ". "
        reason += threshold
    else:
        mode = "expected_cost"
        best = min(options, key=lambda o: o["_objective"])   # égalité → la plus petite vente (min garde la 1re)
        bx = D(best["exit_fraction"])
        rec = "STAY" if bx == 0 else "EXIT" if bx == 1 else "REDUCE"
        rec_x = best["exit_fraction"]
        stay_j = options[0]["objective_usd"]
        if rec == "STAY":
            reason = f"With a {pct(p)}% probability of this {scenario}, staying has the lowest expected cost ({stay_j} USD). "
        else:
            reason = (f"With a {pct(p)}% probability of this {scenario}, {option_label(bx).lower()} has the lowest "
                      f"expected cost ({best['objective_usd']} USD vs {stay_j} USD for staying). ")
        reason += threshold
        if "proxy" in statuses:
            reason += " Exit costs are proxy estimates."
            warnings.append("proxy_quotes: recommendation relies on proxy exit costs; confirm with executable quotes before trading.")

    for o in options:
        del o["_objective"], o["_p_star"]

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


def load_contracts(liquidity=False, fixture_dir=FIXTURE_DIR):
    """Charge les 4 fichiers d'entrée de P3 (lecture seule). liquidity=True → scénario B."""
    suffix = "_liquidity" if liquidity else ""
    names = {"portfolio": "portfolio", "snapshot": "market_snapshot",
             "risk_result": f"risk_result{suffix}", "scenario_request": f"scenario_request{suffix}"}
    return {key: json.loads((Path(fixture_dir) / f"{name}.json").read_text()) for key, name in names.items()}


def decide_position(portfolio, snapshot, risk_result, scenario_request, position_id, estimator=DEFAULT_ESTIMATOR):
    """Décision pour une position, à partir des contrats JSON de P1/P2 (format 11.8)."""
    scenario = scenario_request["scenario"]
    for field, a, b in [("request_id", risk_result["request_id"], scenario_request["request_id"]),
                        ("portfolio_id", risk_result["portfolio_id"], portfolio["portfolio_id"]),
                        ("portfolio_id", scenario_request["portfolio_id"], portfolio["portfolio_id"]),
                        ("scenario_id", risk_result["scenario_id"], scenario["scenario_id"]),
                        ("horizon_days", risk_result["horizon_days"], scenario["horizon_days"])]:
        if a != b:
            raise ValueError(f"Inconsistent inputs: {field} {a!r} != {b!r}")

    position = next((p for p in portfolio["positions"] if p["position_id"] == position_id), None)
    impact = next((p for p in risk_result["positions"] if p["position_id"] == position_id), None)
    if position is None or impact is None:
        raise ValueError(f"Position {position_id!r} missing from portfolio or risk_result")
    if impact.get("conditional_loss_usd") is None:
        raise ValueError(f"No conditional_loss_usd for {position_id!r} in risk_result")

    out = decide(position, snapshot, impact["conditional_loss_usd"], scenario["horizon_days"],
                 scenario_request["assumptions"]["probability"], scenario["scenario_id"], estimator)
    ids = {"decision_id": f"decision_{scenario_request['request_id']}",
           "simulation_id": risk_result["simulation_id"],
           "portfolio_id": portfolio["portfolio_id"],
           "position_id": position_id,
           "scenario_id": scenario["scenario_id"]}
    return {"schema_version": out.pop("schema_version"), **ids, **out}   # ordre des champs de 11.8


def portfolio_summary(portfolio, decisions):
    """Additionne les choix position par position, sans optimisation jointe (section 4.2).

    Les totaux sont la somme des montants affichés par position. Ils valent null tant
    qu'une position est INSUFFICIENT_DATA : on n'additionne pas des choix qui n'existent pas.
    """
    rows, warnings = [], []
    stay_loss = D(0)
    chosen = {"estimated_exit_cost_usd": D(0), "foregone_yield_usd": D(0), "residual_stress_loss_usd": D(0)}
    undecided = []
    for d in decisions:
        by_x = {D(o["exit_fraction"]): o for o in d["exit_options"]}
        stay_loss += D(by_x[D(0)]["residual_stress_loss_usd"])
        x = d["recommended_exit_fraction"]
        if x is None:
            undecided.append(d["position_id"])
        else:
            for key in chosen:
                chosen[key] += D(by_x[D(x)][key])
        rows.append({"position_id": d["position_id"], "recommendation": d["recommendation"],
                     "recommended_exit_fraction": x})

    if undecided:
        warnings.append(f"No portfolio total for the chosen actions: {', '.join(undecided)} "
                        f"returned INSUFFICIENT_DATA.")

    venues = {}
    for p in portfolio["positions"]:
        venues.setdefault(p["exit_venue_id"], []).append(p["position_id"])
    for venue_id, pids in venues.items():
        if len(pids) > 1:
            warnings.append(f"{' and '.join(pids)} share {venue_id}: exit costs are standalone and understate "
                            f"a simultaneous exit (joint haircut, section 7.2).")

    first = decisions[0]
    return {
        "portfolio_id": first["portfolio_id"],
        "simulation_id": first["simulation_id"],
        "scenario_id": first["scenario_id"],
        "method": "sum_of_standalone_decisions",
        "positions": rows,
        "stay_conditional_loss_usd": usd(stay_loss),
        "chosen_actions": None if undecided else {k: usd(v) for k, v in chosen.items()},
        "warnings": warnings,
    }


def decide_portfolio(portfolio, snapshot, risk_result, scenario_request, estimator=DEFAULT_ESTIMATOR):
    """Une décision par position du portefeuille + le résumé additif."""
    decisions = [decide_position(portfolio, snapshot, risk_result, scenario_request, p["position_id"], estimator)
                 for p in portfolio["positions"]]
    return {"decisions": decisions, "summary": portfolio_summary(portfolio, decisions)}


if __name__ == "__main__":
    c = load_contracts()
    got = decide_position(c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"], "aave_01")
    golden = json.loads((FIXTURE_DIR / "decision_result.json").read_text())
    print("aave_01 vs fixture 11.8 :", "IDENTIQUE" if got == golden else "DIFFÉRENT")
    print(json.dumps(got, indent=2))
    print("\n--- ancien test sur données écrites à la main ---")
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
    out = decide(position, snapshot, "150000.00", 7, scenario_id="usde_depeg")
    for o, (c, f, p) in zip(out["exit_options"], expected):
        got = (o["estimated_exit_cost_usd"], o["foregone_yield_usd"], o["break_even_probability"])
        print(o["exit_fraction"], got, "OK" if got == (c, f, p) else f"ATTENDU {(c, f, p)}")
    expected_reason = ("No scenario probability supplied and all quotes are proxies. Reducing by 25% beats "
                       "staying if the user's probability of this depeg exceeds 7.75%.")
    print(out["recommendation"], "| reason", "OK" if out["reason"] == expected_reason else f"KO: {out['reason']}")
    for prob in ["0.05", "0.15", "0.40"]:
        r = decide(position, snapshot, "150000.00", 7, prob)
        print(f"p={prob} ->", r["recommendation"], r["recommended_exit_fraction"])
