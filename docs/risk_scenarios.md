# Les sept scénarios du moteur de risque

Ce document décrit les mécanismes effectivement implémentés, les paramètres des préréglages de `stress_portfolio_01` et la lecture des résultats. Les scénarios sont des conditions « si ce choc se produit », pas des prévisions de marché ni des probabilités d'événement.

## Le même portefeuille, sept expériences

Le portefeuille de test contient six positions synthétiques sur des marchés Ethereum documentés : détention de sUSDe, emprunt Aave USDe/USDC, emprunt Morpho sUSDe/PYUSD, PT-sUSDe Pendle, prêt PYUSD contre sUSDe et prêt RLUSD contre USDe. Les quantités sont hypothétiques ; les observations de marché sont enregistrées. Voir [composition, sources et blocs](stress_portfolio.md).

Un calcul dans l'API est recalculé avec les paramètres soumis, mais utiliser l'API ne rend pas automatiquement le snapshot « live ». Les données de ce portefeuille combinent des observations historiques de plusieurs blocs. Les hypothèses, approximations et données manquantes doivent rester visibles.

| Scénario | Question économique | Préréglage du portefeuille de test |
|---|---|---|
| `usde_depeg` | Que perd-on si USDe décote ? | −5 % USDe, beta sUSDe 1, horizon 7 jours |
| `liquidity_crisis` | Combien coûte une sortie dans un marché moins liquide ? | 80 % de profondeur retirée, sans choc fondamental, 7 jours |
| `combined_crisis` | Que se passe-t-il si les liquidateurs vendent avant notre sortie ? | −30 % USDe et 80 % de profondeur retirée, 7 jours |
| `carry_squeeze` | Le rendement couvre-t-il encore la dette dans le temps ? | sUSDe 0 % annuel, emprunt 60 % annuel, 30 jours |
| `governance_change` | Un changement de seuil ou d'oracle rend-il la position liquidable ? | −27 % USDe, seuils −5 points, transmission oracle 1, 7 jours |
| `node_shock` | Quelles positions sont atteintes par la défaillance d'une dépendance ? | `offchain:ethena_backing`, perte 10 %, 7 jours |
| `liquidation_cascade` | Les ventes forcées déclenchent-elles d'autres liquidations ? | −5 % USDe, profondeur −50 %, absorption arbitrage 80 %, 7 jours |

Les valeurs décimales dans les requêtes sont des fractions : `-0.05` signifie −5 %, `0.60` signifie 60 % annuel ; un déplacement de seuil de `-0.05` signifie −5 **points**, pas −5 % relatif. Ce sont des cas alternatifs : leurs pertes ne s'additionnent pas.

## Exemples chiffrés des préréglages

Ces montants sont les sorties de référence régénérées le 10 octobre 2026 pour les paramètres du tableau précédent et le snapshot enregistré de `stress_portfolio_01`. Ils changent quand les paramètres, les données ou le modèle changent ; ce ne sont pas des valeurs à coder dans le front.

| Scénario | Perte conditionnelle du portefeuille (USD) | Valeur nette finale (USD) |
|---|---:|---:|
| `usde_depeg` | 127 514,63 | 2 411 121,44 |
| `liquidity_crisis` | 216 434,64 | 2 322 201,43 |
| `combined_crisis` | 1 087 608,43 | 1 451 027,64 |
| `carry_squeeze` | 6 481,81 | 2 532 154,26 |
| `governance_change` | 899 084,98 | 1 639 551,09 |
| `node_shock` | 246 688,85 | 2 291 947,22 |
| `liquidation_cascade` | 1 353 679,87 | 1 184 956,20 |

La cascade preneuse de prix est ici un stress extrême : elle atteint un point bas de −99,05 % sur les deux collatéraux avant un rebond proche de −5,1 %. La perte persistante des prêteurs vient de la mauvaise dette réalisée pendant la chute. Comparer le mode attentif à l'impact avant de présenter ce résultat comme une estimation réaliste. Source exacte : `contracts/fixtures/stress_portfolio_01/risk_result*.json`, champs `portfolio.total_conditional_loss_usd` et `portfolio.net_equity_after_usd`.

## Les chiffres communs à tous les scénarios

- **Valeur brute** : quantité × prix du collatéral ou de l'actif détenu.
- **Valeur nette initiale** : valeur brute − dette. Pour le portefeuille de test : 2 538 635,91 USD aux prix enregistrés.
- **Perte conditionnelle** : somme des composantes de perte. Un nombre négatif représente un gain.
- **Valeur nette finale** : valeur nette initiale − perte conditionnelle. Une perte n'est donc pas la valeur restante.
- **Perte du portefeuille** : somme des pertes des positions + éventuel coût supplémentaire de sortie sur des venues partagées. Ce dernier existe au niveau portefeuille, sans être attribué arbitrairement à une seule position.

Pour Aave, `HF = collatéral valorisé par l'oracle × seuil de liquidation / dette` ; HF < 1 rend la position liquidable. Pour Morpho, `LTV = dette / collatéral valorisé par l'oracle` ; LTV > LLTV rend la position liquidable. Ce sont des métriques **par position emprunteuse**, pas un health factor global du portefeuille. « Liquidable » signifie que le seuil est franchi, pas qu'une transaction de liquidation a été exécutée.

Une position prêteuse est différente : elle détient une créance sur des emprunteurs. Sa perte dépend de leur distribution de LTV et de notre part de l'offre du marché, pas d'un HF personnel :

`perte prêteur = part de l'offre × (mauvaise dette + dette restante sous-collatéralisée)`.

Un retrait temporairement impossible faute de liquidité est un délai, pas automatiquement une perte.

## 1. Dépréciation USDe — `usde_depeg`

**Chaîne causale :** décote USDe → nouvelle valeur de USDe/sUSDe/PT → lecture de l'oracle → HF/LTV → éventuelle pénalité et perte des prêteurs.

Le moteur sépare trois mécanismes, appliqués chacun une seule fois : choc de prix de marché (`usde_spot_shock_pct`), atteinte au backing (`backing_impairment_pct`) et réduction du taux de conversion sUSDe (`susde_rate_cut_pct`). Les deux derniers paramètres sont aussi des variations signées : une perte de backing de 10 % s'écrit `-0.10`.

```text
prix USDe après = prix initial × (1 + choc spot) × (1 + choc backing)
prix sUSDe après = prix initial × (1 + beta × choc spot)
                  × (1 + choc backing) × (1 + réduction du taux sUSDe)
prix oracle = prix initial × (1 + transmission × mouvement marché)
              × (1 + réduction du taux sUSDe)
```

La transmission 1 suit le marché ; 0 ignore la décote de marché, mais un oracle sUSDe de taux de conversion voit une réduction de ce taux. Une décote invisible à l'oracle peut protéger temporairement un emprunteur de la liquidation tout en laissant son prêteur exposé à un collatéral insuffisant.

Les PT sont valorisés avec une approximation : `valeur de remboursement / (1 + APY implicite + choc APY)^(jours jusqu'à maturité / 365)`. Le préréglage ajoute 3 points d'APY implicite. La pénalité d'un emprunt liquidable est `facteur de clôture × dette après × bonus de liquidation`.

**À observer dans l'UI :** perte de chaque position, HF/LTV avant-après, composantes `market_repricing`, `backing_impairment`, `liquidation_penalty`, `bad_debt` et `undercollateralized_debt`. Au préréglage −5 %, Morpho franchit son seuil, Aave reste non liquidable et les prêteurs ne perdent pas encore de principal.

**Horizon :** c'est ici un choc statique, sans interpolation quotidienne ni croissance de dette sur 7 jours. Le délai d'oracle est une fenêtre d'action signalée, pas une simulation chronologique complète. Les ventes forcées ne réinjectent pas leur impact dans les prix dans ce scénario.

Source : [usde_depeg.py](../backend/risk/scenarios/usde_depeg.py), [pricing.py](../backend/risk/pricing.py), [lending.py](../backend/risk/lending.py).

## 2. Crise de liquidité — `liquidity_crisis`

**Chaîne causale :** profondeur disponible réduite → coût d'une sortie plus élevé → valeur exécutable inférieure à la valeur comptable. Un choc fondamental facultatif peut aussi modifier les prix.

`k = 1 − exit_liquidity_reduction_pct`. Le coût suit les cotations de sortie enregistrées lorsqu'elles couvrent la taille. La courbe est interpolée ; au-delà de la plus grande cotation, le moteur utilise une extrapolation annoncée. En l'absence de courbe, il utilise le proxy de profondeur :

```text
coût proxy(Q) = Q² / (k × profondeur + Q)
coût avec cotations en crise(Q) = k × coût normal(Q / k)
```

Les positions sortant sur la même venue sont regroupées pour chiffrer le coût collectif. Le supplément par rapport aux sorties individuelles est `shared_liquidity_penalty_usd`.

**À observer :** `execution_haircut`, valeur exécutable et supplément collectif. Pour les prêteurs, le moteur estime la liquidité immédiatement retirable depuis l'offre moins les emprunts ; il ne simule pas leur vente du collatéral sur un DEX.

**Limite :** simulation d'une sortie à la profondeur de crise, sans trajectoire quotidienne ni cascade de prix.

Source : [liquidity_crisis.py](../backend/risk/scenarios/liquidity_crisis.py), [liquidity.py](../backend/risk/liquidity.py).

## 3. Choc combiné — `combined_crisis`

**Chaîne causale :** dépeg → liquidations → collatéral saisi vendu sur les venues de crise → notre sortie passe derrière ces ventes → coût additionnel pour les positions partageant la venue.

Le moteur exécute d'abord le dépeg puis valorise la sortie du collatéral restant. Pour une taille Q, derrière des ventes forcées F :

`coût de notre sortie = coût(F + Q) − coût(F)`.

Il compare ce résultat au **même choc avec les mêmes profondeurs, sans ventes de liquidateurs devant nous**. L'excès mesure la contagion par la liquidité partagée. Additionner les pertes de dépeg et de liquidité calculées séparément donne généralement un autre résultat, car la sortie séparée utilise une valeur avant dépeg.

**À observer :** comparaison avec/sans ventes forcées, pénalité de liquidation, haircut de sortie et supplément collectif.

**Limite :** un seul passage ; les prix de sortie dégradés ne repassent pas dans les oracles. Pour cette boucle, choisir la cascade.

Source : [combined_crisis.py](../backend/risk/scenarios/combined_crisis.py).

## 4. Compression du carry — `carry_squeeze`

**Chaîne causale :** rendement sUSDe faible → dette qui croît plus vite que le collatéral → HF/LTV qui se dégrade → seuil franchi → pénalité pour l'emprunteur et éventuellement mauvaise dette pour le prêteur.

Ici, l'horizon intervient directement. Le moteur applique des **intérêts simples**, même si les champs sont nommés APY :

```text
t = horizon en jours / 365
dette après = dette initiale × (1 + taux d'emprunt × t)
quantité de collatéral après = quantité initiale × (1 + taux de fourniture × t)
valeur sUSDe après = valeur initiale × max(1 + taux sUSDe × t, 0)
```

À 60 % annuel pendant 30 jours, la dette augmente d'environ 4,93 %. Un LTV initial de 88 %, avec collatéral inchangé, devient environ 92,34 %, au-dessus du LLTV 91,5 %.

Les prêteurs gagnent leur rémunération de fourniture, mais leurs emprunteurs subissent aussi cette dérive. Lorsqu'un taux d'emprunt est forcé, le taux de fourniture est approché par `taux d'emprunt × utilisation`. Les PT se rapprochent de leur maturité et peuvent avoir un choc d'APY implicite facultatif.

**À observer :** `negative_carry` (peut être négatif si gain), HF/LTV, date approximative de franchissement pour les emprunts et comparaison avec les taux du snapshot sur le même horizon. Le coût du squeeze par rapport aux taux actuels n'est pas la même quantité que la perte par rapport à aujourd'hui.

**Limite :** taux constants, intérêts simples, pas de modèle dynamique de funding, d'utilisation ou de courbe de taux, ni ventes forcées avec boucle de prix.

Source : [carry_squeeze.py](../backend/risk/scenarios/carry_squeeze.py).

## 5. Gouvernance ou changement d'oracle — `governance_change`

**Chaîne causale :** nouveaux seuils/régime d'oracle → même dépeg → nouvelles positions liquidables → pertes additionnelles.

Le moteur modifie d'abord le snapshot de travail : `nouveau seuil = ancien seuil + liquidation_threshold_shift`, borné entre 0 et 0,99. `oracle_switch_pass_through` remplace la transmission. `target_markets` permet de limiter le changement à certains identifiants ; null cible les marchés de prêt pris en charge.

Il applique ensuite le dépeg. La comparaison rejoue ce **même dépeg sur les anciens paramètres** : l'excès isole le coût du changement de gouvernance.

**À observer :** changements listés, HF/LTV, positions nouvellement liquidables et différence par rapport au cas sans changement.

**Limite :** décision de gouvernance imposée par l'utilisateur ; pas de probabilité de vote, de délai de timelock ou de migration de contrats simulée.

Source : [governance_change.py](../backend/risk/scenarios/governance_change.py).

## 6. Choc sur une dépendance — `node_shock`

**Chaîne causale :** nœud ciblé → mécanisme économique identifié → valorisation des expositions → rapprochement avec les chemins du graphe.

| Nœud ciblé | Mécanisme implémenté |
|---|---|
| `asset:USDe`, `protocol:ethena`, `offchain:*` | Perte du backing USDe, appliquée via le scénario de dépeg |
| `asset:sUSDe` | Réduction du taux de conversion sUSDe, visible par ses oracles |
| Un autre stablecoin pris en charge, par exemple `asset:PYUSD` | Décote de cet actif dans la valorisation ; la dette en USD diminue pour son emprunteur |
| Autre `protocol:*`, `market:*` ou `asset:PT-*` | Perte supposée d'une part de la valeur brute des positions ciblées ; perte d'un emprunteur plafonnée à sa valeur nette positive |

`loss_pct` est ici une **ampleur positive** : 0,10 signifie une destruction de valeur de 10 %. Les chemins du graphe expliquent les dépendances ; ils ne distribuent pas automatiquement 10 % de perte à chaque voisin. La propagation financière provient des règles de valorisation et de prêt. Un chemin avec une perte nulle à cette taille peut être valide ; une exposition non prise en charge doit être signalée.

**À observer :** nœud initial, positions touchées, chemins causaux, composantes de perte et avertissements de couverture.

**Limites :** tous les nœuds `offchain:*` utilisent actuellement le mécanisme backing USDe, sans modèle de part propre à chaque dépositaire. Une décote de stablecoin ne modélise pas sa présence dans le backing Ethena. Un échec de protocole est une perte supposée, pas la reproduction technique d'un exploit. Les venues et oracles demandent respectivement un scénario de liquidité ou de gouvernance.

Source : [node_shock.py](../backend/risk/scenarios/node_shock.py), [contagion.py](../backend/risk/contagion.py).

## 7. Cascade de liquidation — `liquidation_cascade`

**Chaîne causale :** choc initial → emprunteurs liquidables → vente de collatéral → prix plus bas → nouvelles liquidations. C'est le scénario à choisir pour montrer une boucle de contagion.

Les emprunteurs du marché sont représentés par des tranches de dette classées par LTV. Les positions emprunteuses du portefeuille sont utilisées comme repli lorsqu'une distribution couvrant le couple collatéral/dette manque, pour éviter d'ajouter deux fois la même exposition au marché.

Dans chaque tour, le moteur prend les emprunteurs les plus sous-collatéralisés, liquide jusqu'à 5 % de leur dette initiale par morceau, puis **recalcule le prix après chaque morceau** :

```text
prix après / prix initial = (1 + choc initial) × (1 − décote marginale(Q))
décote marginale(Q) ≈ variation du coût de sortie pour un dollar supplémentaire
entre deux tours : Q ← Q × (1 − absorption d'arbitrage)
```

USDe et sUSDe ont leurs propres venues. Un oracle qui ne transmet pas le choc peut interrompre la boucle de liquidation de son marché, sans supprimer la perte économique d'un prêteur.

Deux comportements sont possibles :

- **Preneurs de prix** : liquident une tranche si elle est rentable au prix courant, puis subissent son impact de marché.
- **Attentifs à leur impact** (`liquidators_internalize_impact = true`) : réduisent la tranche ou s'arrêtent si leur propre vente consomme le bonus de liquidation. Il peut rester de la dette liquidable mais non rentable à liquider, appelée `stuck_debt`.

La mauvaise dette est comptée **au prix de chaque tranche liquidée**. Un rebond ultérieur ne l'efface pas. La dette restante sous-collatéralisée est valorisée au prix final. Le résultat est comparé au **même choc initial sans boucle de ventes forcées**.

**À observer :** pertes avec/sans feedback, amplification du mouvement de prix, prix initial/final/point bas par actif, dette liquidée et collatéral vendu par tour, mauvaise dette, dette bloquée et `converged`. Les montants de dette du bloc cascade sont à l'échelle des marchés modélisés ; les pertes des positions prêteuses ne représentent que notre part. L'amplification est un rapport de mouvements de prix, pas un montant en dollars ni un multiplicateur de perte du portefeuille.

**Tours et horizon :** un tour n'est pas une journée. L'horizon de 7 jours n'est pas transformé en sept tours. L'absorption est une hypothèse par tour, sans cadence calendaire calibrée.

**Arrêt numérique :** les micro-liquidations sont rejetées sous un seuil fixe lié à la dette initiale ; le moteur rejette aussi un ajout trop petit pour changer le solde en virgule flottante. Une limite de tranches et de 50 tours évite un calcul sans fin ; atteindre une limite marque le résultat incomplet. Une position auparavant bloquée mais redevenue sûre au prix final n'est plus annoncée comme liquidable.

**Limites économiques :** une venue par collatéral, absence d'arbitrage explicite entre USDe et sUSDe, distribution des emprunteurs dépendante du snapshot, profondeur et absorption à calibrer. Les paramètres de backing/PT interviennent dans la valorisation finale du scénario ; le déclencheur de la boucle utilise actuellement le choc spot initial et le beta, pas un état complet combinant tous les chocs. Le résultat est un stress de modèle, pas une prédiction d'un épisode réel.

Source : [cascade.py](../backend/risk/cascade.py), [liquidation_cascade.py](../backend/risk/scenarios/liquidation_cascade.py).

## Lire l'incertitude sans la confondre avec une prévision

L'analyse rejoue le même scénario 256 fois en tirant uniformément les entrées incertaines dans leurs plages déclarées. Les entrées vérifiées concernées restent fixes. Le bandeau P5–P95 montre l'intervalle central de 90 % des **pertes simulées**, pas 90 % de probabilité que le scénario survienne.

Par exemple, « 654 871 USD – 1,15 M USD » signifie une fourchette de **perte du portefeuille** entre son 5e et son 95e percentile. La borne haute n'est pas le maximum. Chaque position possède ses propres percentiles ; additionner leurs bornes ne donne pas les bornes du portefeuille. Le point blanc est la médiane, le trait coral le calcul de référence avec les hypothèses originales.

L'histogramme compte les simulations par intervalle de perte en USD. Le tableau des facteurs affiche une corrélation de rang de Spearman entre hypothèse et perte, entre −1 et +1 : ce score n'est ni un montant, ni une probabilité, ni une preuve de causalité isolée. Les résultats hors connexion peuvent utiliser l'analyse du préréglage alors que le curseur utilise la surface ; le bandeau de l'UI le signale.

Source : [uncertainty.py](../backend/risk/analytics/uncertainty.py), [RiskEngine.tsx](../frontend/src/RiskEngine.tsx).

## Parcours pour tester et retrouver l'origine d'un nombre

1. Ouvrir Scenario Lab : choisir le scénario, modifier les paramètres puis cliquer **Run scenario**. Aucun résultat ne doit être présenté comme un nouveau calcul avant ce clic.
2. Lire l'impact sur cette page : perte et valeur nette par position, métrique de liquidation de la position sélectionnée et graphe de propagation du run.
3. Ouvrir Risk Engine : scénario/horizon soumis, composantes, cause à effet, détail des positions et traces avec formules, entrées, unités et provenance.
4. Pour une cascade, comparer « initial shock only » au résultat avec feedback, puis lire les tours. Pour la gouvernance et le carry, utiliser leurs comparaisons spécifiques.
5. Pour un nombre incertain, développer sa ligne et lire sa valeur exacte et son percentile. Pour un coût de sortie, vérifier s'il vient d'une cotation, d'une extrapolation ou d'un proxy.

Le dashboard et le graphe de dépendances initial décrivent le portefeuille de départ ; bouger un curseur ne doit pas les transformer en un résultat de stress. La page Execution est une étape distincte, non modifiée par ce correctif.

## Reproduire depuis le code

Les entrées sont dans [contracts/fixtures/stress_portfolio_01](../contracts/fixtures/stress_portfolio_01), notamment `portfolio.json`, `market_snapshot.json`, `dependency_graph.json` et les sept `scenario_request*.json` (le fichier `scenario_request_severe.json` est une variante plus sévère du dépeg, pas un huitième moteur).

```bash
# Tests de la cascade, puis suite complète
.venv/bin/python -m pytest backend/risk/tests/test_cascade.py -q
.venv/bin/python -m pytest backend tests -q -p no:cacheprovider

# Recalcul des résultats, analyses et surface pour le portefeuille de test
.venv/bin/python -m backend.risk.regenerate contracts/fixtures/stress_portfolio_01
```

L'API `/simulate` produit le résultat et les traces ; `/analyze` produit les comparaisons analytiques, courbes, sensibilités et incertitudes. Les fichiers enregistrés sont des sorties du moteur, pas des nombres inventés dans le front. L'architecture et l'historique sont décrits dans [risk_engine_plan.md](risk_engine_plan.md).

## Préparer un scénario dans le chatbot

Le chatbot est disponible dès que le portefeuille initial est chargé, avant la première simulation. Saisir une description en français ou en anglais, par exemple :

- `USDe baisse de 10 %, liquidité baisse de 80 %, sur 7 jours` → crise combinée.
- `Crée une cascade avec USDe -8 %, liquidité -60 %, sur 7 jours` → cascade.
- `Rendement sUSDe -5 %, emprunt 65 % sur 30 jours` → compression du carry.
- `Gouvernance : baisse des seuils de 3 points, USDe -15 %` → changement de gouvernance.
- `Défaillance du backing Ethena : perte 20 % sur 7 jours` → choc de dépendance.

La réponse est une proposition, avec chaque paramètre marqué « Your text » ou « Portfolio preset ». Le détail JSON montre le scénario exact prévu pour le moteur, y compris les autres paramètres du préréglage. Cliquer **Use in Scenario Lab** charge les contrôles ; cliquer ensuite **Run scenario** déclenche le calcul habituel. Le chatbot ne produit pas de chiffres de perte pour une proposition et ne simule pas lors de sa préparation.

Cette version utilise un interpréteur local contraint ([scenarioDraft.ts](../frontend/src/actions/scenarioDraft.ts)), sans modèle de langage ni clé API. Elle reconnaît les sept mécanismes existants, leurs contrôles exposés et un horizon de 1 à 30 jours. Elle refuse une quantité hors limites, un pourcentage non attribuable, un nœud absent ou un choc d'actif non pris en charge ; elle ne construit pas un huitième modèle à partir d'un récit libre. Les valeurs sont à écrire après leur paramètre, avec une unité (% ou points), et l'horizon en jours. Les paramètres non exposés dans les contrôles, comme le beta ou l'absorption de l'arbitrage, restent au préréglage ; tenter de les modifier dans le texte est refusé. Pour exécuter exactement les paramètres soumis, utiliser le mode API : le mode enregistré garde les limites de sa surface et affiche les paramètres ignorés.

Après un run, les questions sur le HF/LTV ou les positions continuent de lire les résultats présents. Mentionner USDe dans une question ne relance plus une simulation.

Vérification : `cd frontend && npm run check:assistant`.
