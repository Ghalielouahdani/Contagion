# Backtest historique : API, vérification et limites

Le moteur est un simulateur conditionnel : « si ce choc arrive, quel est son impact ? ». Ce document distingue le rejeu de données passées de la validation prédictive et complète le [rapport existant](risk_backtest.md).

## 1. Ce qui a été vérifié et recalculé

Le backtest déjà présent dans [backend/risk/backtest](../backend/risk/backtest/) utilise des historiques DefiLlama, Pendle, Binance et Chainlink. J'ai réexécuté son calcul et ajouté un export traçable des résultats, de la couverture des séries et des hashes des entrées/code.

- **11 477 observations PT** : erreur absolue médiane 0,7386 bp, p95 25,0412 bp, p99 47,0151 bp. Le pire écart signé atteint **−8,9770 %** : bonne médiane ne signifie pas formule exacte sur tous les points.
- **145 fenêtres quotidiennes** de portefeuille : erreur absolue moyenne 3 671,58 USD, soit 5,92 bps de la NAV de référence de 6 202 968,85 USD ; corrélation 0,5626 ; erreur absolue p95 13 742,56 USD. Il y a **9 jours** où la perte est sous-estimée de plus de 5 bps de NAV.
- **12 fenêtres de baisse USDe ≥0,5 %** : rapport médian des mouvements sUSDe/USDe ≈0,92. Ce résultat soutient le beta 1 comme hypothèse de travail ; il ne garantit pas son caractère prudent dans chaque crise future.
- **10 octobre 2025** : low Binance USDE/USDT 0,65 ; USDe DefiLlama horaire 0,97206256 ; Chainlink 0,99293808. Les signaux de marché, de venue et d'oracle sont différents.

Les [résultats détaillés générés](backtests/results.md) et le [JSON](backtests/historical_results.json) font foi pour les chiffres précis. **Verdict : les tests de briques passent, mais cela ne valide pas un backtest prédictif complet ni des liquidations historiques réelles.**

## 2. Quelles API prendre ?

Une API unique de prix ne fournit pas les oracles, les seuils de liquidation, les emprunteurs et la liquidité nécessaires. La combinaison pertinente est la suivante ; « testé » désigne une collecte réussie enregistrée dans le dépôt, « documenté » désigne une capacité de fournisseur qui n'a pas encore été intégrée à ce backtest.

| Donnée requise | Source et requête | Statut ici | Limite concrète |
|---|---|---|---|
| Prix USD USDe/sUSDe/stablecoins | [DefiLlama SDK officiel](https://github.com/DefiLlama/api-sdk), `GET https://coins.llama.fi/prices/historical/{timestamp}/{chain:address}` | Historiques horaires enregistrés | Timestamp le plus proche, fraîcheur/confiance à contrôler ; pas une cotation vendable pour une taille donnée |
| Bloc Ethereum à une date | DefiLlama `GET /block/ethereum/{timestamp}`, puis RPC `eth_getBlockByNumber` | À utiliser pour un futur rejeu archive | Le bloc retourné peut être postérieur à la date ; un futur collecteur doit redescendre au bloc antérieur |
| Taux sUSDe/USDe et état des contrats | RPC archive `eth_call` au numéro de bloc ; [documentation Ethereum archive](https://ethereum.org/en/developers/docs/nodes-and-clients/archive-nodes/) et [Geth RPC](https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-eth) | Lecture archive pertinente pour un futur snapshot | Un RPC normal peut garder les blocs sans pouvoir relire leur état ; toutes les méthodes historiques ne sont pas garanties |
| Fournisseur RPC | [dRPC Ethereum](https://drpc.org/docs/ethereum-api), endpoint public `https://eth.drpc.org`, ou un RPC archive dédié | Capacité à vérifier selon les dates et quotas | Disponibilité et quotas non garantis ; l'essai PublicNode a refusé l'archive sans token personnel |
| APY et états Morpho | [API Morpho officielle](https://docs.morpho.org/developers/api/morpho/) : REST `.../apy/history`, `.../state/history`, ou GraphQL `historicalState` avec timestamps | Documenté, pas rejoué ici | Couverture/indexation à vérifier ; ne remplace pas la distribution de dette des emprunteurs |
| Bougies historiques CEX | [Binance Spot API](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints), `/api/v3/klines` avec `startTime`, `endTime`, `interval` | USDEUSDT horaire dans le dataset | Low d’une venue en USDT ; pas prix global USD ni prix oracle |
| Prix d’oracle historiques | [Chainlink historique](https://docs.chain.link/data-feeds/historical-data), `getRoundData` et `updatedAt` | 849 rounds du feed USDe/USD dans la phase courante | Phases antérieures et changement de feed à reconstruire |
| Positions emprunteurs Morpho | [Historique utilisateur Morpho](https://docs.morpho.org/api/markets/user-market-position-history/), logs + état archive | Documenté | Nécessite les adresses de tous les emprunteurs actifs au bloc ; pas seulement ceux encore présents aujourd'hui |
| PT, APY implicite, TVL Pendle | [API officielle Pendle](https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview), [OpenAPI](https://api-v2.pendle.finance/core/docs), `GET /core/v3/{chainId}/markets/{address}/historical-data` | Historiques APY présents dans le dataset | Marché déployé à la date requise ; prix historique ≠ quote historique pour un ordre |
| Oracle, LT/LLTV, bonus, indices de dette Aave/Morpho | Contrats au bloc archive + logs de gouvernance et de positions | Source identifiée, pas intégrée au rejeu | Relire la configuration/oracle utilisés à cette date, pas celle du snapshot 2026 |
| Profondeur/quotes DEX historiques | État AMM archive et quoter exécuté au bloc ; inventaire des pools et routes existant alors | À implémenter | Un quote API « maintenant » ne valide pas une exécution ancienne ; reproduire tailles, frais, décimales, gaz |
| Funding, couverture/CEX, garde Ethena | Sources de financement et rapports datés des contreparties ; [Ethena : off-exchange settlement](https://docs.ethena.fi/backing-custody-and-security/overview/off-exchange-settlement-in-detail) | Non collecté | Toute l'information n'est pas publique ni on-chain ; prix seuls insuffisants pour distinguer depeg et perte de backing |

Les endpoints historiques Morpho proposent notamment des fenêtres `one_day`, `seven_days`, `thirty_days`, `ninety_days`, `one_year`, `inception` ; le GraphQL permet un intervalle de dates explicite. Vérifier les champs et la couverture pour **chaque** marché avant de construire un dataset. Pour Pendle, utiliser la version publique v3 et consulter le schéma de `time_frame`, `timestamp_start`, `timestamp_end`, `fields` ; ne pas compter sur les endpoints privés de son interface.

Les données de rendement ne sont pas automatiquement couvertes par le prix historique gratuit DefiLlama. Un rendement sUSDe peut être estimé depuis les taux de conversion lus aux blocs archivés ; le replay actuel utilise plutôt les prix historiques sUSDe/USDe. Ni cette série ni les seuls prix ne fournissent le funding de toutes les contreparties.

## 3. Comment le backtest actuel calcule ses sorties

### Prix PT

```text
prix_modèle = prix_USDe / (1 + APY_Pendle)^(jours_à_maturité / 365)
erreur_relative = prix_modèle / prix_PT_publié − 1
```

Les observations sont appariées à l'heure et excluent les PT à moins de 3 jours de maturité. APY et prix observés peuvent être liés par construction : c'est surtout une vérification de cohérence du pricing, pas une prévision indépendante.

### Beta sUSDe

Pour chaque paire disponible à 1 h ou 24 h : `x = USDe1/USDe0 − 1`, `y = sUSDe1/sUSDe0 − 1`. Le beta OLS est `cov(x,y)/var(x)`. Le ratio médian `y/x` est calculé séparément sur les baisses USDe d'au moins 0,5 %. Les fenêtres horaires/quotidiennes peuvent se chevaucher ; le nombre de fenêtres n'est pas celui d'événements indépendants.

### Replay portefeuille

Les quantités du portefeuille `verified_2026_10_10` sont fixées et appliquées à d'anciens prix. Pour chaque fenêtre quotidienne utilisable :

```text
perte_prix_proxy = −[Q_USDe×variation_USDe + Q_sUSDe×variation_sUSDe + Q_PT×variation_PT]
choc_fourni_au_moteur = USDe_final / USDe_initial − 1
perte_moteur = somme des composantes de perte du scénario usde_depeg
erreur = perte_prix_proxy − perte_moteur
MAE = moyenne(abs(erreur))
```

Le code appelle la même implémentation de scénario que le moteur, mais ce chemin d'audit ne passe pas par tout le contrat JSON `simulate()`/graph/report. Il conserve les paramètres de marchés du fixture 2026 et remplace les prix ainsi que l'APY/maturité PT. Le PT à plus courte maturité restant au moins 30 jours est sélectionné à chaque date : cela constitue un panier contrefactuel, pas un wallet historique avec ses opérations de roll, frais et flux externes.

Le taux sUSDe de ce replay est dérivé de `prix_sUSDe/prix_USDe`, pas d'une lecture archive `convertToAssets` à chaque bloc. Les stablecoins de dette, leurs intérêts et les frais d'exécution ne sont pas inclus dans le P&L proxy observé. La NAV de référence est celle des allocations 2026 ; elle ne reconstitue pas la NAV de chaque ancienne journée.

### Épisode de crise et oracle

Le pass-through ajusté est `mouvement_Chainlink / mouvement_Binance` ≈2,0774 %. Il est calculé **après l'événement**, sur des minima qui ne sont pas forcément simultanés. Dans le portefeuille actuel, le verdict de liquidation Morpho change lorsqu'on utilise cette réponse plutôt qu'une transmission complète du print Binance. Il s'agit d'une comparaison de scénarios contrefactuels : on n'a pas ici vérifié les transactions de liquidation de positions historiques.

Une bougie Binance en USDT n'est pas automatiquement un prix USD : le replay suppose USDT à 1 USD. Un point horaire DefiLlama ne mesure pas tout le minimum intrajournalier ni la capacité de vente d'un portefeuille.

## 4. Biais temporels et portée de la validation

Le collecteur arrondit les timestamps à l'heure la plus proche. `_near()` peut apparier sUSDe à ±2 heures, donc utiliser une observation postérieure à l'heure visée. Le replay reçoit aussi volontairement le mouvement USDe final connu. **Ce n'est pas une simulation sans look-ahead utilisable pour revendiquer une performance prédictive.**

Le dataset est clairsemé, particulièrement pour sUSDe/PT. Les 145 fenêtres disponibles sont un sous-ensemble des jours calendaires et peuvent avoir un biais de disponibilité. Le feed Chainlink ne couvre que la phase actuelle de l'agrégateur. Les anciennes réponses HTTP brutes et les timestamps non arrondis ne sont pas tous conservés dans ce dataset : les hashes ajoutés permettent d'identifier le fichier reproduit, pas de reconstruire ces informations perdues.

À éviter : appeler la formule PT « exacte », déduire qu'un beta 1 est toujours prudent, affirmer que les liquidations historiques sont justes parce que le verdict d'un portefeuille actuel semble cohérent, ou dire qu'il n'y a eu qu'un seul vrai stress dans toute l'histoire. Ce rapport étudie des épisodes précis et un échantillon donné.

## 5. Reproduire et documenter

Depuis la racine du dépôt :

```bash
# Offline : utilise le dataset committé.
.venv/bin/python -m backend.risk.backtest.run
.venv/bin/python -m backend.risk.backtest.run --json

# Régénère les résultats JSON et le rapport Markdown avec provenance.
.venv/bin/python -m backend.risk.backtest.document
.venv/bin/python -m backend.risk.backtest.document --output-dir /tmp/bsa-history-report

# Recollecte réseau ; remplace le dataset enregistré.
.venv/bin/python -m backend.risk.backtest.fetch
.venv/bin/python -m backend.risk.backtest.fetch --chainlink

# Tests offline.
.venv/bin/python -m pytest backend/risk/tests/test_backtest.py backend/risk/tests/test_backtest_document.py -q
```

L'export conserve la date de collecte originale, les fournisseurs, la couverture temporelle de chaque série et les SHA-256 du dataset compressé, des fixtures d'entrée et du code utilisé. Le statut est `partial_ex_post_validation_not_predictive_backtest`.

Le collecteur Pendle existant utilise encore l'endpoint v2. Pour une nouvelle intégration, préférer l'API publique v3 documentée et vérifier la compatibilité des champs : le rapport n'a pas silencieusement changé la source des données déjà enregistrées.

## 6. Ce qui manque pour vérifier tout le portefeuille

Construire un snapshot historique neuf ; ne pas conserver les paramètres 2026 en remplaçant seulement les prix.

1. Choisir des marchés existants à la date étudiée, inclure les marchés ensuite fermés pour éviter la survivance, et fixer les quantités avant le choc.
2. Relire prix, taux de conversion sUSDe, oracles, LT/LLTV, bonus, supply/borrow, indices d'intérêts et maturités aux blocs initiaux ; conserver hashes de blocs et timestamps exacts.
3. Reconstruire les emprunteurs et buckets pondérés par dette à la date initiale. Les agrégats de marché seuls ne donnent pas les pertes prêteurs.
4. Reproduire les quotes aux tailles voulues depuis l'état AMM archive. TVL et prix historiques ne donnent pas le coût de sortie ; le carnet CEX actuel n'est pas un carnet historique.
5. Rejouer le chemin intrajournalier et comparer aux logs de liquidation, dette remboursée, collatéral saisi, bad debt et proceeds réalisés. Un rebond final n'efface pas une mauvaise dette réalisée au creux.
6. Comptabiliser apports/retraits, frais, remboursements et rolls si l'on compare à un vrai portefeuille.
7. Calibrer sur une période puis figer les paramètres pour une période distincte, avec aucune observation future dans les entrées. Rapporter erreurs USD/bps, faux positifs/négatifs, timing et couverture des données.
8. Vérifier sur de nombreuses observations la couverture des intervalles d'incertitude ; les 256 tirages actuels ne sont pas une validation historique des probabilités.

Les sources identifiées couvrent beaucoup des données publiques, mais aucune API publique unique ne garantit toutes les données offchain des contreparties Ethena et toute l'exécution historique. Ces trous doivent rester visibles plutôt que remplacés par des paramètres prétendument observés.

Guide de chaque sortie et de son calcul : [risk_engine_explained.md](risk_engine_explained.md).
