# Backtest du moteur de risque

Un stress test ne se « vérifie » pas sur un scénario qui n'a jamais eu lieu. On peut en revanche confronter chaque brique du moteur à ce que l'USDe, le sUSDe et les PT-sUSDe ont réellement fait (février 2024 → octobre 2026), et étudier notamment le krach CEX du 10 octobre 2025. Le rejeu utilise toutefois les allocations et paramètres de prêt actuels : ce n'est pas une reconstitution historique complète.

```bash
python -m backend.risk.backtest.fetch          # télécharge l'historique (une fois ; fichier committé)
python -m backend.risk.backtest.run            # rapport ; --json pour les chiffres bruts
pytest backend/risk/tests/test_backtest.py     # garde-fous sur l'historique enregistré
```

Données (`backend/risk/backtest/data/history.json.gz`) : prix horaires on-chain DefiLlama (USDe, sUSDe, 14 PT-sUSDe), APY implicite horaire Pendle, bougies horaires Binance USDe/USDT, et toutes les rounds du flux Chainlink USDe/USD (`0xa569…f961`, le `BASE_FEED_1` de l'oracle Morpho sUSDe/PYUSD vérifié), lues on-chain. Les prix DefiLlama du sUSDe et des PT sont clairsemés : chaque test n'utilise que des observations appariées.

## Résultats

| Test | Résultat | Verdict |
|---|---|---|
| Formule PT = USDe / (1 + APY implicite)^(jours/365) | 11 477 obs. horaires : erreur médiane **0,7 bp**, p95 25 bp, p99 47 bp | Bonne cohérence médiane ; pire écart −8,98 %, pas exactitude générale |
| Bêta sUSDe/USDe (défaut moteur : 1) | Les 12 jours où l'USDe a baissé d'au moins 0,5 %, le sUSDe a baissé **0,92×** autant (médiane) | Hypothèse compatible avec ces fenêtres ; prudence non garantie |
| Choc d'APY implicite PT (préréglages : 0 ou +3 pts) | Saut sur 24 h : p99 **+2,7 pts** | +3 pts cohérent avec l'historique |
| Pire mouvement de l'USDe | On-chain : −3,1 % sur 24 h ; Chainlink : 0,977 (hack Bybit, 21/02/2025) ; Binance : **0,65** (10/10/2025) | Le préréglage −5 % dépasse déjà tout ce qu'un oracle a vu |
| Replay quotidien du portefeuille vérifié | 145 jours : corrélation 0,56, erreur absolue moyenne 3,7 k$ (6 bp de NAV), le moteur surestime en moyenne de 1,8 k$/jour (portage non modélisé sur 1 jour) | Suit une partie du P&L de prix proxy ; 9 jours sous-estimés >5 bp |
| 10/10/2025 : verdict de liquidation | Voir ci-dessous | Verdict contrefactuel sensible à la réponse oracle ; transactions historiques non validées |

## Le 10 octobre 2025 : marché ≠ oracle ≠ venue

| Source | Plus bas USDe |
|---|---|
| Binance (une venue CEX) | **0,6500** (clôture de l'heure à 0,9365) |
| Pools on-chain (DefiLlama, horaire) | 0,9721 |
| Chainlink USDe/USD (lu par l'oracle Morpho) | **0,99294** |

Le flux Chainlink n'a transmis que **2 %** du mouvement Binance. Rejoué dans le moteur avec le portefeuille vérifié :
- choc Binance −35 %, oracle Morpho configuré à pass-through 1 → **Morpho liquidable** ;
- même choc, avec la réponse réelle du flux → **aucune position éligible dans le modèle** : ce n'est pas une observation de transactions historiques ;
- choc on-chain −2,8 % → aucune liquidation, perte de marquage 279 k$.

À retenir pour les scénarios : `usde_spot_shock_pct` est un prix **soutenu sur toutes les venues**. Un print isolé sur une CEX se modélise avec `oracle_pass_through_override` proche de 0 (ou en crise de liquidité), pas comme un depeg. Le hack Bybit montre l'inverse : quand le mouvement est large, Chainlink le voit (0,977), même plus bas que l'échantillon horaire on-chain (0,9926).

Le même soir, le PT-sUSDe nov. 2025 a perdu jusqu'à 4,9 % en une heure alors que l'APY implicite horaire n'a bougé que de 6,96 % à 7,25 % : c'est un print de liquidité du pool Pendle, pas un choc de taux. Ce risque relève du scénario de crise de liquidité (coût de sortie Pendle), pas de `pt_implied_apy_shock`.

## Corrections apportées au moteur

L'évaluation du code a mis au jour un défaut de calcul, corrigé et couvert par des tests (`test_properties.py`) :

1. **Pertes supérieures à la net equity.** Un emprunt n'avait aucune responsabilité limitée : à −80 %, la démo affichait Morpho à −1,45 M$ pour 1,0 M$ de net equity, et la pénalité était comptée même quand la collatérale ne couvrait plus la dette. Désormais, la composante `limited_liability` (négative) plafonne la perte à la net equity (`usde_depeg`, `carry_squeeze`, `liquidity_crisis`, `combined_crisis`), comme le faisait déjà `node_shock`.
2. **Une seule liquidation Aave.** Avec un close factor de 50 %, un HF compris entre 0,95 et LT × (1 + bonus) reste sous 1 après le premier appel. Les liquidateurs recommencent : c'est désormais modélisé (`metrics.liquidate`).
3. **Saisie non plafonnée et mesurée au prix de l'oracle.** La collatérale saisie est plafonnée à ce qui reste (le reste de la dette est radié), valorisée au prix de marché, et aucune liquidation n'a lieu si elle vaut moins que la dette remboursée (cohérent avec `cascade.py`).

Effet sur les jeux de données : `verified_2026_10_10` crise de liquidité 7,11 M$ → 6,03 M$ (l'Aave et le Morpho ne peuvent pas perdre plus que leur net equity), combinée 5,87 M$ → 5,62 M$ ; `stress_portfolio_01` sévère 997 k$ → 775 k$. Les valeurs golden de la démo (depeg −5 %, liquidité −80 %) sont inchangées.

## Limites

- Les épisodes étudiés ne couvrent pas toutes les crises possibles : le backtest vérifie certaines briques (prix, facteurs, lecture d'oracle), pas la sévérité des scénarios extrêmes.
- La cascade de liquidations et les coûts de sortie ne sont pas backtestés : il faudrait l'historique des liquidations (Morpho/Aave) et des cotations.
- Le P&L de prix proxy du replay n'inclut ni la variation des stablecoins de dette, ni les intérêts, ni les frais : leur impact omis n'est pas mesuré par ce test.
- Le replay fournit au modèle le mouvement USDe final connu et conserve les paramètres de marchés du fixture 2026. Les prix sUSDe peuvent être appariés à ±2 heures : ce n'est pas un test prédictif sans look-ahead.

Méthode auditée, API et limites détaillées : [historical_backtest.md](historical_backtest.md). [Rapport généré avec provenance](backtests/results.md). Guide de chaque sortie : [risk_engine_explained.md](risk_engine_explained.md).
