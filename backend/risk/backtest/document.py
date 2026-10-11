"""Export the existing historical audit with input/code fingerprints and limitations.

python -m backend.risk.backtest.document
This is an ex-post replay, not a prediction or a historical lending-state replay.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.risk.backtest import run
from backend.risk.report import MODEL_VERSION

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "docs" / "backtests"
LIMITATIONS = [
    "Ex-post replay: each day's final USDe move is an input, not a forecast.",
    "Fixed 2026 synthetic allocations and lending configuration; not reconstructed historical wallet/market state.",
    "PT front market is selected per date with >=30 days remaining; not one investable portfolio with recorded rolls.",
    "sUSDe prices may be matched within +/-2 hours; collection rounds timestamps to nearest hour.",
    "PT price and implied yield can share pricing inputs: their agreement is not independent predictive validation.",
    "USDEUSDT Binance prices assume USDT=USD; no historical USDT conversion in this audit.",
    "Chainlink covers rounds of the current aggregator phase, not all previous phases.",
    "No historical borrower distribution, actual liquidation transactions, DEX exit costs or cascade calibration.",
    "No actual wallet cash flows, debt-stablecoin returns, accrued borrowing costs or execution fees in realised proxy P&L.",
    "Observed oracle pass-through is fitted from event lows, potentially at different times: explanatory, not forward-known.",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coverage(series: dict | list) -> dict:
    times = [int(t) for t in series] if isinstance(series, dict) else [int(row[0]) for row in series]
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    return {"observations": len(times), "first_utc": iso(min(times)) if times else None,
            "last_utc": iso(max(times)) if times else None}


def build() -> dict:
    with gzip.open(run.DATA, "rt") as stream:
        raw = json.load(stream)
    paths = [run.DATA] + sorted((ROOT / "backend/risk").glob("*.py")) + sorted((ROOT / "backend/risk/scenarios").glob("*.py"))
    paths += [Path(run.__file__), Path(__file__)] + [run.FIXTURE / (name + ".json") for name in ("portfolio", "market_snapshot", "scenario_request")]
    coverage = {key: _coverage(raw[key]) for key in ("usde", "susde", "binance_usde_ohlc", "chainlink_usde_usd")}
    coverage["pt"] = {key: {"price": _coverage(m["price"]), "implied_apy": _coverage(m["implied_apy"])} for key, m in raw["pt"].items()}
    return {"model_version": MODEL_VERSION, "status": "partial_ex_post_validation_not_predictive_backtest",
            "provenance": {"dataset_fetched_at": raw.get("fetched_at"), "sources": raw.get("sources"),
                           "sha256": {str(p.relative_to(ROOT)): _hash(p) for p in paths}},
            "coverage": coverage, "limitations": LIMITATIONS, "results": run.run_all()}


def markdown(document: dict) -> str:
    r = document["results"]
    pt, rep, beta, crash = (r[k] for k in ("pt_pricing", "portfolio_replay", "susde_beta_1d", "crash_replay"))
    coverage_table = "| Série | Points | Première observation UTC | Dernière observation UTC |\n|---|---:|---|---|\n"
    for key in ("usde", "susde", "binance_usde_ohlc", "chainlink_usde_usd"):
        coverage = document["coverage"][key]
        coverage_table += f"| {key} | {coverage['observations']:,} | {coverage['first_utc']} | {coverage['last_utc']} |\n"
    return f'''# Résultats du backtest historique — rapport reproductible

Statut : **validation partielle ex post**, pas backtest prédictif complet. Modèle `{document['model_version']}`. Dataset récupéré le `{document['provenance']['dataset_fetched_at']}`.

| Mesure | Résultat recalculé |
|---|---:|
| Observations PT appariées | {pt['observations']:,} |
| Erreur absolue PT médiane | {pt['median_abs_bps']:.4f} bps |
| Erreur PT p95 / p99 | {pt['p95_abs_bps']:.4f} / {pt['p99_abs_bps']:.4f} bps |
| Pire erreur PT relative signée | {pt['worst']['error']:.4%} |
| Jours de replay disponibles | {rep['days']} |
| NAV de référence des allocations | {rep['nav']:,.2f} USD |
| Erreur absolue moyenne du replay | {rep['mae_usd']:,.2f} USD ({rep['mae_usd']/rep['nav']*10000:.2f} bps de NAV) |
| Erreur absolue p95 | {rep['p95_abs_error_usd']:,.2f} USD |
| Erreur moyenne (réalisé proxy − moteur) | {rep['mean_error_usd']:,.2f} USD |
| Corrélation des pertes proxy/moteur | {rep['correlation']:.4f} |
| Jours sous-estimés de plus de 5 bps de NAV | {rep['underpredicted_days']} |
| Ratio médian sUSDe/USDe en baisse ≥0,5 % | {beta['stress_down_median_ratio']:.4f}, sur {beta['stress_down_events']} fenêtres |

Le scénario reçoit le mouvement USDe final connu. L'erreur moyenne négative signifie une perte moteur en moyenne supérieure au P&L de prix proxy ; il reste {rep['underpredicted_days']} jours de sous-estimation au-delà du seuil. Le pire écart PT ne doit pas être masqué par la bonne médiane.

## Couverture des données

{coverage_table}

Ces nombres sont des points de série, pas des observations appariées ni des jours indépendants. La couverture des 14 marchés PT est détaillée dans le JSON.

## Épisode du 10 octobre 2025

| Source | Plus bas dans la fenêtre |
|---|---:|
| Binance USDE/USDT, sans correction USDT/USD | {crash['binance_low']:.8f} |
| DefiLlama USDe, points horaires | {crash['onchain_low']:.8f} USD |
| Chainlink USDe/USD | {crash['chainlink_low']:.8f} USD |

Pass-through ajusté après l'événement : {crash['observed_pass_through']:.4%} du mouvement Binance. Dans le portefeuille contrefactuel actuel, Morpho est éligible avec le choc Binance transmis intégralement ; aucune position n'est éligible avec la réponse d'oracle ajustée ou le choc on-chain. **Ces verdicts ne sont pas des liquidations historiques effectivement observées.**

## Rapport détaillé du code existant

```text
{run.report(r)}
```

Les libellés « predicted » de ce rapport désignent une sortie conditionnelle alimentée par le choc observé, pas une prévision hors échantillon.

## Provenance et limites

Le [JSON complet](historical_results.json) contient résultats, couverture temporelle par série, sources, hashes du dataset, des inputs et du code. La commande `python -m backend.risk.backtest.document` régénère ce document offline.

''' + "\n".join("- " + limitation for limitation in document["limitations"]) + "\n\nMéthode et API : [historical_backtest.md](../historical_backtest.md). Lecture des sorties : [risk_engine_explained.md](../risk_engine_explained.md).\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = build()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "historical_results.json").write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "results.md").write_text(markdown(document))
    print(f"Exported {document['status']} to {args.output_dir}")


if __name__ == "__main__":
    main()
