# Risk engine — plan et feuille de route (P2)

Objectif : un moteur de risque **juste d'abord, différenciant ensuite**. La plupart des équipes feront « prix −5 % → perte −5 % ». Nous montrons ce que le nom du projet promet : **la contagion**, c'est-à-dire comment un choc se propage, s'amplifie, et où sont les points de rupture.

Références : blueprint sections 4.2, 7, 11 · [backend/risk/README.md](../backend/risk/README.md) · [contracts/](../contracts/README.md)

---

## Niveau 1 : le socle (non négociable, en premier)

**Règle : tant que les valeurs de référence ne passent pas, on ne touche à rien d'autre.** Un moteur faux qui a l'air sophistiqué est pire que tout devant un jury.

- [x] **Valorisation** des 4 positions : sUSDe = parts × taux de change × prix USDe ; PT = prix USDe / (1 + APY implicite)^(jours/365) ; collatéral, dette, net equity.
  Contrôle : on retrouve le brut à 10,0 M$, la dette à 3,8 M$ et le net à 6,2 M$.
- [x] **Scénario A (depeg)** : prix de marché ≠ prix de l'oracle (pass-through par marché + override), bêta sUSDe, dépréciation du backing, choc de rendement PT. HF Aave, LTV Morpho, distance de liquidation.
- [x] **Scénario B (crise de liquidité)** : valeur de marché vs valeur exécutable, haircut = taille² / (profondeur + taille), sortie seule par position, sortie conjointe par venue partagé au niveau du portefeuille.
- [x] **Décomposition des pertes** : `market_repricing`, `backing_impairment`, `liquidation_penalty`, `execution_haircut` ; la somme est exacte et il n'y a aucun double comptage.
- [x] **Tests** : aucun choc → aucun changement ; monotonie ; pass-through 0 vs 1 ; maturité du PT ; réconciliation des positions avec le total ; **valeurs de référence** :

| Scénario        | Valeurs à reproduire                                                                  |
|-----------------|---------------------------------------------------------------------------------------|
| Depeg −5 %      | HF Aave 1,4167 → 1,3458 · LTV Morpho reste 0,6667 · perte totale **523 320,57**        |
| Liquidité −80 % | perte totale **920 646,49**, dont pénalité de venue partagé **251 015,13**             |

---

## Niveau 2 : les différenciateurs (par ordre impact / effort)

### 1. Points de rupture (reverse stress test) · effort faible · impact énorme
On ne demande plus « que se passe-t-il à −5 % ? » mais « **à quel niveau je meurs ?** ». Formule fermée quand elle existe, sinon recherche numérique du seuil.

Avec les fixtures :
- **Aave** devient liquidable quand USDe tombe à **0,706** (depeg de −29,4 %).
- **Morpho** est **immunisé contre le depeg de marché et contre une perte de backing de l'USDe** (oracle sur le taux de change, USDe fixé à 1 $), mais il est liquidé dès **−27,1 % de baisse du taux sUSDe**.

Phrase de pitch : *« deux positions qui ont l'air identiques meurent de deux chocs différents. »*

- [x] Seuils par position et par type de choc (depeg de marché, perte de backing, baisse du taux sUSDe)
- [x] Seuils au niveau du portefeuille : −10 % de NAV dès un depeg de 6,2 % ; −20 % à 12,4 % ; −50 % à 30,6 %

### 2. Concentration factorielle · effort faible · impact énorme pour le pitch
On décompose chaque perte par facteur : prix USDe, taux sUSDe, rendement PT, liquidité.

Avec les fixtures : **6,2 M$ « diversifiés » sur 4 protocoles se comportent comme 10 M$ d'exposition à un seul facteur, USDe, soit un levier effectif de 1,6x.**

- [x] Sensibilité ($ par 1 % de choc) par facteur et par position
- [x] Levier effectif par facteur = exposition / net equity (USDe 1,61x · sUSDe 1,13x · rendement PT 0,13x)

### 3. Surfaces de sensibilité + tornado · effort moyen · très visuel
- [x] Heatmaps : depeg × pass-through de l'oracle (scénario A), réduction de liquidité × choc fondamental (scénario B), et n'importe quelle paire de paramètres via `sensitivity.grid`
- [x] Tornado : quelle hypothèse fait le plus bouger le résultat (la réponse à « vos hypothèses sont fausses, et alors ? »)
- [x] Rapide pour des curseurs en direct : un scénario = ~45 µs, grille de 441 points ≈ 20 ms en Python pur (NumPy inutile à cette taille)

### 4. Cascade de liquidations · effort élevé · LE différenciateur
L'effet domino, c'est la vraie contagion endogène :
1. Le choc initial rend des emprunteurs liquidables **dans tout le marché**, pas seulement nous.
2. Les liquidateurs vendent leur collatéral dans le même pool.
3. Le prix baisse encore, ce qui crée de nouvelles liquidations.
4. On itère jusqu'à convergence (point fixe).

Sortie : un **facteur d'amplification** (exemple illustratif : « −5 % initial → −8,3 % final »), le nombre de rounds et le volume liquidé.

- [ ] Donnée demandée à P1 : distribution des emprunteurs par prix de liquidation (Aave, Morpho). Sinon, distribution supposée étiquetée `assumed`.
- [ ] Garde-fous : convergence garantie (nombre max d'itérations, tolérance), résultat étiqueté comme modèle.

### 5. Presets calibrés sur l'historique · effort faible · crédibilité
Des scénarios inspirés d'épisodes réels plutôt que de chiffres inventés :
- USDC, mars 2023 (autour de 0,87) ;
- crash d'octobre 2025 : l'USDe a fortement décroché sur Binance alors que les pools on-chain sont restés bien plus proches du peg. C'est l'illustration parfaite de « prix de marché ≠ prix de l'oracle ≠ venue ».

- [ ] **Faire vérifier les chiffres, sources et dates par P1** avant de les mettre dans la démo

---

## Moteur relié au graphe de dépendances (fait)

Chaque perte est reliée à son **chemin de contagion** dans le graphe de P1, par exemple `pendle_01 → PT-sUSDe → sUSDe → USDe`, avec la preuve et la confiance de chaque lien.

**Le graphe ne décide pas seul qui est touché.** Un lien manquant donnerait une perte de zéro sans avertissement, ce qui est la pire erreur pour un outil de risque. Les montants viennent de la valorisation, et les deux sont **recoupés dans les deux sens** :
- **trou du graphe** : perte sans chemin → la dépendance manque dans le graphe (signalé) ;
- **exposition non modélisée** : chemin sans perte → l'exposition manque dans le moteur (signalé) ;
- **hubs** : les nœuds dont dépendent plusieurs positions. Dans la démo, **l'USDe porte les 4 positions, soit toute la NAV de 6,2 M$** ; le venue sUSDe est partagé par deux positions.

Ce qu'il faut demander à P1 : passer les liens de `assumed` à `verified` (adresse de contrat + bloc). La confiance affichée pour chaque perte monte automatiquement.

## Valeur pour le fonds : combien l'outil fait gagner (fait)

Le module `backend/risk/analytics` traduit chaque scénario en **dollars** pour le gérant (contrat `risk_analytics.json`, fixtures `risk_analytics*.json`). Tout est conditionnel au scénario : on ne promet jamais un rendement, on chiffre ce qu'une décision rapporte **si** le scénario arrive.

| Analyse                     | Ce qu'on dit au fonds                                                                                   | Chiffre (fixtures)                                              |
|-----------------------------|---------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| Concentration factorielle   | « Vous pensez être diversifié sur 4 protocoles ; c'est un seul pari sur l'USDe. »                        | 10,0 M$ d'exposition USDe = **1,61x la NAV**                     |
| Points de rupture           | « Voici le prix de l'USDe auquel vous perdez chaque position. »                                         | Aave à −29,4 % ; Morpho à −27,1 % de taux sUSDe ; **−10 % de NAV dès un depeg de 6,2 %** |
| Dé-risquage ciblé           | « Pour la même protection, voici où couper : moins cher qu'une baisse uniforme de toutes les lignes. »  | −5 % : protection de 267 k$ pour 51,7 k$ au lieu de 58,3 k$ (**6,7 k$ économisés**, ~11 bp de NAV) ; agir rentable si P(scénario) > **19 %** |
| Protection liquidation      | « Dépensez X aujourd'hui pour éviter une pénalité Y. »                                                  | −30 % : **426 $** de désendettement évitent **45 000 $** de pénalité Aave ; avec 6 h de retard d'oracle, encore 43,5 k$ récupérables pendant la fenêtre |

À −30 %, le chiffre clé est la break-even : le plan ciblé est rentable dès **3,2 %** de probabilité du scénario.

### Ce que dit la sensibilité (pitch)

- **À −5 %, seul compte la taille du choc** (depeg, backing, taux sUSDe, bêta). Les paramètres de liquidation n'ont **aucun impact** : on est loin des seuils.
- **À −30 %, le seuil de liquidation Aave devient critique** : 5 points de moins (0,85 → 0,80) font passer le HF sous 0,95, le close factor saute à 100 % et la pénalité passe de 0 à **90 k$**. → **P1 doit vérifier ce paramètre en priorité.**
- **La heatmap montre la frontière de liquidation** : oracle à pass-through 0, aucune liquidation quel que soit le depeg ; pass-through 1, Aave et Morpho tombent dès −30 %. → **Le type d'oracle Morpho est la donnée la plus importante à confirmer.**
- **Crise de liquidité** : après la sévérité de la crise, c'est la profondeur du venue sUSDe (partagé par deux positions) qui pèse le plus.

### Choix de modélisation tranchés (critère : chaque dollar affiché doit être juste)

- **Pénalité de liquidation = règles réelles des protocoles**, pas une borne prudente : Aave rembourse 50 % de la dette tant que HF ≥ 0,95 (100 % en dessous) ; Morpho n'a pas de close factor. Surestimer la perte pousserait le fonds à trop vendre, ce qui coûte de l'argent.
- **Trois chocs distincts** : depeg de marché, perte de backing de l'USDe, baisse du taux sUSDe (`susde_rate_cut_pct`). Un oracle « taux de change, USDe fixé à 1 $ » ne voit que le dernier. C'est ce qui rend le récit Aave vs Morpho exact.
- **Retard d'oracle = fenêtre d'action chiffrée** : coût du désendettement pendant la fenêtre vs pénalité évitée.
- **Gain de liquidation publié de façon prudente** : pénalité évitée − coût. La perte de valeur évitée sur le collatéral vendu est affichée à part (c'est du dé-risquage, pas de la liquidation).

### Limites à dire honnêtement

- Les coûts de sortie reposent sur une profondeur *proxy* ; avec de vraies cotations (P1/P3) les économies changeront.
- Les économies du dé-risquage ciblé sont modestes sur ces fixtures (positions aux coûts proches) ; elles grandissent quand les liquidités des venues diffèrent fortement.

## Niveau 3 : la finition qui fait pro

### 6. Traçabilité de chaque chiffre
Chaque résultat transporte son arbre de calcul : formule, entrées et `source_type`. Dans l'interface, on clique sur « −150 000 $ » et on voit `3 000 000 × (1,00 − 0,95)` avec la provenance de chaque entrée.
- [ ] À concevoir **dès le départ** (c'est presque gratuit si c'est prévu tôt, très coûteux à rajouter après)

### 7. Pas de probabilités fabriquées
Pertes conditionnelles et seuils uniquement, jamais une « perte attendue » inventée. C'est un argument de rigueur à dire explicitement dans le pitch.

---

## Architecture

```
backend/risk/
├── valuation.py      prix et valeurs des positions (fonctions pures)
├── scenarios/        un fichier par scénario + registre (calqué sur les contrats modulaires)
├── metrics.py        HF, LTV, distance de liquidation
├── liquidity.py      haircuts, sortie conjointe par venue
├── analytics/        points de rupture, attribution factorielle, grilles de sensibilité
├── cascade.py        boucle de liquidations
└── trace.py          arbre de calcul attaché à chaque résultat
```

- **Fonctions pures et déterministes** : même entrée, même sortie, donc faciles à tester et à mettre en cache.
- **Float64 vectorisé avec NumPy à l'intérieur, Decimal arrondi en sortie.** Tolérance de 0,01 $ sur les valeurs de référence.
- **Nouvelles sorties = ajout sans casse** : bloc `analytics` optionnel dans `risk_result`, donc on reste en schéma v1 (voir les recettes d'extension dans `contracts/README.md`).

## Coordination avec les autres

| Avec | Quoi                                                                                             | Quand           |
|------|--------------------------------------------------------------------------------------------------|-----------------|
| P1   | Type d'oracle Morpho (pass-through 0 ou 1 ?) : toute l'histoire Aave vs Morpho en dépend          | Dès le kickoff  |
| P1   | Distribution des emprunteurs pour la cascade ; données historiques des presets                    | Avant l'étape 4 |
| P3   | Haircuts sous stress et profondeurs de crise par venue                                           | Avec le socle   |
| P4   | Prévoir l'affichage : points de rupture, levier factoriel, heatmap, tornado, cascade, traces      | Dès l'étape 2   |

## Ordre d'exécution

À chaque étape la démo reste fonctionnelle ; si le temps manque, on coupe par la fin.

1. [x] Socle + valeurs de référence (les tests passent)
2. [x] Points de rupture + concentration factorielle (pitch déjà différenciant)
3. [x] Grilles de sensibilité + tornado
4. [ ] Cascade de liquidations
5. [ ] Presets historiques + traçabilité complète

## Questions ouvertes

- [ ] Durée du hackathon et nombre de personnes sur P2 → la cascade (étape 4) est-elle réaliste ?
- [ ] Type d'oracle réel du marché Morpho retenu (à confirmer par P1)
