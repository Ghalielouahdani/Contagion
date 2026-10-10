"""backend/execution/hedging.py — P3 : univers de couverture pour le mode « crise en cours ».

Ce qu'on peut réellement chiffrer avec les données du projet :
- convertir un actif exposé en stablecoin NON lié à Ethena (USDC, USDT, PYUSD, RLUSD) ;
  la route vers USDC est déjà cotée dans le snapshot (venues de sortie), les autres peuvent l'être
  à la demande avec la même API que P1 (KyberSwap, backend/discovery/exit_quotes.py) ;
- un actif n'est une couverture que s'il n'est PAS choqué par le scénario.

Ce qu'on ne peut pas chiffrer (aucune source de prix dans le projet) : vente à découvert d'USDe ou
d'ENA, options, assurance contre le dépeg. Ils sont listés comme « non chiffrés », jamais inventés.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.risk.model import Venue
from backend.risk.scenarios.node_shock import mechanism

HEDGE_STABLES = ("USDC", "USDT", "PYUSD", "RLUSD")
USDE_FAMILY = ("USDe", "sUSDe", "PT-sUSDe")
DEPEG_PARAMS = ("usde_spot_shock_pct", "backing_impairment_pct", "susde_rate_cut_pct")
REGISTRY = Path(__file__).resolve().parents[1] / "adapters" / "registry" / "ethereum.json"
UNPRICED = [
    {"instrument": "Short USDe or ENA perpetual futures",
     "why_unpriced": "No perpetual venue or funding-rate source in the project APIs."},
    {"instrument": "Put options on USDe / sUSDe",
     "why_unpriced": "No options market data in the project APIs."},
    {"instrument": "USDe depeg cover (insurance)",
     "why_unpriced": "No cover provider pricing in the project APIs."},
]


def _registry_tokens() -> dict:
    return json.loads(REGISTRY.read_text())["tokens"]


def shocked_assets(scenario_request: dict) -> dict[str, str]:
    """Actifs dont le prix bouge dans ce scénario (une couverture ne peut pas en faire partie)."""
    scenario = scenario_request["scenario"]
    sid, params = scenario["scenario_id"], scenario.get("parameters", {})
    nonzero = lambda name: params.get(name) not in (None, "0", "0.00", 0) and float(params[name]) != 0
    if sid in ("usde_depeg", "combined_crisis", "governance_change", "liquidation_cascade"):
        if any(nonzero(p) for p in DEPEG_PARAMS):
            return {a: "USDe depeg in this scenario" for a in USDE_FAMILY}
        return {}
    if sid == "liquidity_crisis":
        return {a: "fundamental value shock" for a in USDE_FAMILY} if nonzero("fundamental_value_shock_pct") else {}
    if sid == "node_shock":
        node = params["node_id"]
        kind = mechanism(node)
        if kind in ("usde_backing", "susde_exchange_rate"):
            return {a: f"{node} shock reaches the USDe family" for a in USDE_FAMILY}
        if kind == "stablecoin_depeg":
            return {node.partition(":")[2]: f"{node} is the shocked node"}
    return {}   # carry_squeeze, protocol failures : pas de choc de prix d'actif


def hedge_universe(snapshot: dict, scenario_request: dict, quote_source=None) -> dict:
    """Stablecoins de couverture : prix, choqué ou non, routes chiffrables depuis chaque actif exposé."""
    tokens = _registry_tokens()
    shocked = shocked_assets(scenario_request)
    exposed = {v["asset"]: vid for vid, v in snapshot.get("exit_venues", {}).items() if v.get("asset") in USDE_FAMILY}
    assets = []
    for stable in HEDGE_STABLES:
        price = snapshot.get("prices_usd", {}).get(stable)
        routes = []
        for asset, venue_id in sorted(exposed.items()):
            if venue_id.endswith("_" + stable.lower()):
                routes.append({"from": asset, "status": "snapshot_quotes", "venue_id": venue_id})
            elif quote_source is not None and asset in tokens and stable in tokens:
                routes.append({"from": asset, "status": "on_demand_quote", "source": "KyberSwap (P1 aggregator)"})
            else:
                why = f"{asset} or {stable} not in P1 token registry" if (asset not in tokens or stable not in tokens) \
                    else "no quote in snapshot; on-demand quotes disabled"
                routes.append({"from": asset, "status": "unavailable", "reason": why})
        affected = stable in shocked
        assets.append({
            "asset": stable,
            "issuer": tokens.get(stable, {}).get("issuer"),
            "price_usd": None if price is None else price["value"],
            "shocked_in_scenario": affected,
            "shock_reason": shocked.get(stable),
            "usable_as_hedge": price is not None and not affected and any(r["status"] != "unavailable" for r in routes),
            "routes": routes,
        })
    warnings = []
    if "USDT" in [a["asset"] for a in assets]:
        warnings.append("Aave prices USDe collateral with a capped USDT/USD feed (P1 discovery): a USDT shock also "
                        "moves the Aave oracle.")
    return {"shocked_assets": shocked, "assets": assets, "unpriced_instruments": UNPRICED, "warnings": warnings}


def kyberswap_quote_source(snapshot: dict):
    """Source de cotation à la demande (réseau) : même route KyberSwap que P1, actif exposé → stablecoin."""
    from backend.discovery.exit_quotes import quote_curve   # import paresseux : réseau uniquement à l'appel

    prices = {k: float(v["value"]) for k, v in snapshot.get("prices_usd", {}).items()}

    def source(asset: str, stable: str) -> dict | None:
        if asset not in prices or stable not in prices:
            return None
        return quote_curve(asset, prices[asset], stable=stable, stable_price_usd=prices[stable])
    return source


def _venue(venue_id: str, raw: dict) -> Venue:
    return Venue(venue_id, raw["asset"], float(raw["effective_depth_usd"]), raw["quote_method"],
                 float(raw.get("fee_rate", 0)), float(raw.get("gas_usd", 0)), Venue.curve_from_quotes(raw.get("quotes", [])))


def rotation_strategies(model, timing: str, universe: dict, quote_source=None) -> list[dict]:
    """« Convertir en stablecoin X » pour chaque couverture utilisable dont toutes les routes sont chiffrées.

    USDC est déjà la destination des venues du snapshot (identique à exit_all) : on ne le répète pas.
    """
    strategies = []
    for hedge in universe["assets"]:
        stable = hedge["asset"]
        if stable == "USDC" or not hedge["usable_as_hedge"] or quote_source is None:
            continue
        priced_from = {r["from"] for r in hedge["routes"] if r["status"] == "on_demand_quote"}
        venues, choices, missing = {}, {}, []
        for pid, c in model.contexts.items():
            asset = c.venue.asset if c.venue else None
            if asset not in USDE_FAMILY:
                continue
            try:
                model.option(pid, timing, "sell", "1.00")
            except ValueError:
                continue
            raw = quote_source(asset, stable) if asset in priced_from else None   # sans route chiffrée : on garde
            if raw is None:
                missing.append(pid)
                continue
            venues[pid] = _venue(f"venue:{asset.lower()}_{stable.lower()}_on_demand", raw)
            choices[pid] = ("sell", "1.00")
        if not choices:
            continue
        result = model.evaluate(timing, choices, venues)
        del result["_total"]
        strategies.append({
            "strategy_id": f"rotate_into_{stable.lower()}",
            "description": f"Sell every USDe-family exposure into {stable} (not shocked in this scenario), "
                           "priced on on-demand KyberSwap quotes.",
            "choices": {pid: {"action": a, "fraction": f} for pid, (a, f) in choices.items()},
            "same_as": None,
            "unpriced_positions": missing,   # gardées : aucune route chiffrée vers ce stablecoin
            **result,
        })
    return strategies
