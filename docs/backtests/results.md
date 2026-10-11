# Résultats du backtest historique — rapport reproductible

Statut : **validation partielle ex post**, pas backtest prédictif complet. Modèle `risk-v0.1`. Dataset récupéré le `2026-10-10T19:04:55+00:00`.

| Mesure | Résultat recalculé |
|---|---:|
| Observations PT appariées | 11,477 |
| Erreur absolue PT médiane | 0.7386 bps |
| Erreur PT p95 / p99 | 25.0412 / 47.0151 bps |
| Pire erreur PT relative signée | -8.9770% |
| Jours de replay disponibles | 145 |
| NAV de référence des allocations | 6,202,968.85 USD |
| Erreur absolue moyenne du replay | 3,671.58 USD (5.92 bps de NAV) |
| Erreur absolue p95 | 13,742.56 USD |
| Erreur moyenne (réalisé proxy − moteur) | -1,784.12 USD |
| Corrélation des pertes proxy/moteur | 0.5626 |
| Jours sous-estimés de plus de 5 bps de NAV | 9 |
| Ratio médian sUSDe/USDe en baisse ≥0,5 % | 0.9188, sur 12 fenêtres |

Le scénario reçoit le mouvement USDe final connu. L'erreur moyenne négative signifie une perte moteur en moyenne supérieure au P&L de prix proxy ; il reste 9 jours de sous-estimation au-delà du seuil. Le pire écart PT ne doit pas être masqué par la bonne médiane.

## Couverture des données

| Série | Points | Première observation UTC | Dernière observation UTC |
|---|---:|---|---|
| usde | 23,096 | 2024-02-20T00:00:00+00:00 | 2026-10-10T18:00:00+00:00 |
| susde | 6,302 | 2024-03-06T08:00:00+00:00 | 2026-10-10T19:00:00+00:00 |
| binance_usde_ohlc | 9,512 | 2025-09-09T12:00:00+00:00 | 2026-10-10T19:00:00+00:00 |
| chainlink_usde_usd | 849 | 2024-07-12T08:01:35+00:00 | 2026-10-10T03:59:11+00:00 |


Ces nombres sont des points de série, pas des observations appariées ni des jours indépendants. La couverture des 14 marchés PT est détaillée dans le JSON.

## Épisode du 10 octobre 2025

| Source | Plus bas dans la fenêtre |
|---|---:|
| Binance USDE/USDT, sans correction USDT/USD | 0.65000000 |
| DefiLlama USDe, points horaires | 0.97206256 USD |
| Chainlink USDe/USD | 0.99293808 USD |

Pass-through ajusté après l'événement : 2.0774% du mouvement Binance. Dans le portefeuille contrefactuel actuel, Morpho est éligible avec le choc Binance transmis intégralement ; aucune position n'est éligible avec la réponse d'oracle ajustée ou le choc on-chain. **Ces verdicts ne sont pas des liquidations historiques effectivement observées.**

## Rapport détaillé du code existant

```text
1. PT pricing formula vs observed PT-sUSDe prices
   11477 hourly obs: median |error| 0.7 bp, p95 25.0 bp, p99 47.0 bp, mean -0.7 bp
2. Factor assumptions
   sUSDe beta to USDe: 0.45 (24h, 4164 pairs), 0.29 (1h, 3940 pairs); engine default 1.0
   on 12 days USDe fell >= 0.5%, sUSDe fell a median 0.92x as much (the low all-days beta is price noise, not decoupling)
   PT implied APY 24h jump: p99 +2.69%, max +14.50% (2024-05-15 14:00); engine default pt_implied_apy_shock 0
3. Worst moves in history
   USDe on-chain: 1h -3.00% (2025-12-09 17:00), 24h -3.09%, 7d -3.01%, min price 0.9721
   USDe Binance low 0.6500 (2025-10-10 21:00, closed the hour at 0.9365)
   Chainlink USDe/USD min 0.97721 (2025-02-21 15:00)
   sUSDe on-chain 24h -1.30%; PT on-chain 1h -4.90% (2025-10-10 22:00)
4. Portfolio replay (verified portfolio, daily)
   145 days, NAV 6,202,969: correlation realised/predicted 0.56, MAE 3,672 USD, p95 |error| 13,743 USD, mean (realised - engine) -1,784 USD
   days the engine under-predicted the loss by > 3,101 USD: 9
   worst realised days:
     2025-12-04 00:00: USDe -0.48%, realised loss 45,351, engine 47,427
     2025-11-06 00:00: USDe -0.25%, realised loss 22,198, engine 24,560
     2024-10-24 00:00: USDe +0.14%, realised loss 17,704, engine -12,929
     2025-10-07 00:00: USDe -0.25%, realised loss 17,078, engine 24,512
     2025-02-01 00:00: USDe -0.20%, realised loss 16,950, engine 19,143
5. Oracle vs market, lowest USDe price per source
   bybit_hack_2025_02_21: on-chain hourly 0.9926, Binance n/a, Chainlink 0.9772
   cex_crash_2025_10_10: on-chain hourly 0.9721, Binance 0.6500, Chainlink 0.9929
6. Oct 10, 2025 replay
   lows: Binance 0.6500, on-chain 0.9721, Chainlink 0.99294 (from 1.00021)
   PT 2025-11-27: 0.9908 -> 0.9555 (-3.57%); implied APY 6.96% -> peak 7.25%
   engine, Binance shock, configured oracles: shock -35.00% -> loss 3,453,738 USD, liquidatable ['morpho_01']
   engine, Binance shock, observed Chainlink response: shock -35.00% -> loss 3,453,738 USD, liquidatable none
   engine, on-chain shock: shock -2.79% -> loss 279,454 USD, liquidatable none
   observed oracle pass-through of the CEX move: 0.021
```

Les libellés « predicted » de ce rapport désignent une sortie conditionnelle alimentée par le choc observé, pas une prévision hors échantillon.

## Provenance et limites

Le [JSON complet](historical_results.json) contient résultats, couverture temporelle par série, sources, hashes du dataset, des inputs et du code. La commande `python -m backend.risk.backtest.document` régénère ce document offline.

- Ex-post replay: each day's final USDe move is an input, not a forecast.
- Fixed 2026 synthetic allocations and lending configuration; not reconstructed historical wallet/market state.
- PT front market is selected per date with >=30 days remaining; not one investable portfolio with recorded rolls.
- sUSDe prices may be matched within +/-2 hours; collection rounds timestamps to nearest hour.
- PT price and implied yield can share pricing inputs: their agreement is not independent predictive validation.
- USDEUSDT Binance prices assume USDT=USD; no historical USDT conversion in this audit.
- Chainlink covers rounds of the current aggregator phase, not all previous phases.
- No historical borrower distribution, actual liquidation transactions, DEX exit costs or cascade calibration.
- No actual wallet cash flows, debt-stablecoin returns, accrued borrowing costs or execution fees in realised proxy P&L.
- Observed oracle pass-through is fitted from event lows, potentially at different times: explanatory, not forward-known.

Méthode et API : [historical_backtest.md](../historical_backtest.md). Lecture des sorties : [risk_engine_explained.md](../risk_engine_explained.md).
