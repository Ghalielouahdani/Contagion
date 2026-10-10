# Journal P3 : ce qui a été fait jusqu'ici

> Module P3 : *Decision, Liquidity & Exit Optimization*
> Branche : `feat/p3` (poussée sur GitHub)
> État : étapes 0, 1, 1bis, 2 et 3 terminées sur 8

---

## 1. Le projet en deux minutes

### Le problème
Un gestionnaire de fonds (fictif) détient **4 positions DeFi** pour 10 M$ au total. Toutes dépendent du même stablecoin, **USDe**, émis par Ethena.

Un *stablecoin* est un jeton censé valoir toujours 1 $. Quand il descend sous 1 $, par exemple à 0,95 $, on parle de **depeg** (perte de parité).

| Position | Ce que c'est | Valeur brute | Dette | Valeur nette |
|---|---|---|---|---|
| `ethena_susde_01` | On détient du sUSDe (USDe « placé » qui rapporte 7 %/an) | 2,0 M$ | – | 2,0 M$ |
| `aave_01` | On a déposé 3 M$ d'USDe en garantie sur Aave et emprunté 1,8 M$ d'USDC | 3,0 M$ | 1,8 M$ | 1,2 M$ |
| `morpho_01` | Pareil sur Morpho, avec du sUSDe en garantie et 2 M$ d'USDC empruntés | 3,0 M$ | 2,0 M$ | 1,0 M$ |
| `pendle_01` | On détient des « PT-sUSDe », des jetons qui valent 1 sUSDe à une date future et s'achètent aujourd'hui avec une décote | 2,0 M$ | – | 2,0 M$ |

### Le découpage en 4 modules

```
P1 (données)  ──►  P2 (risque)  ──►  P3 (décision, c'est nous)  ──►  P4 (dashboard / API)
prix, pools,       "si la crise       "faut-il garder,                 affichage pour
rendements         arrive, combien    réduire ou vendre ?"             les juges
                   je perds ?"
```

Les modules ne s'appellent pas directement : ils échangent des **fichiers JSON au format figé**, rangés dans `contracts/`. Chacun peut donc avancer sans attendre les autres, à partir de **fixtures**, c'est-à-dire des fichiers d'exemple aux valeurs cohérentes entre elles.

### La question de P3
> Pour une position donnée : **STAY** (garder), **REDUCE** (vendre une partie) ou **EXIT** (tout vendre) ? Et est-ce que la sortie vaut ce qu'elle coûte ?

---

## 2. Les concepts financiers, sur l'exemple aave_01

Pour aave_01, P2 a calculé que **si USDe tombe à 0,95 $, la position perd 150 000 $**. 3 M$ de garantie × 5 % de baisse = 150 000 $.

On teste 5 options : vendre **0 %, 25 %, 50 %, 75 % ou 100 %** de la position. On le fait **avant** la crise, aux prix normaux : c'est une décision de prévention.

> **Position avec dette :** vendre 25 % d'aave_01 veut dire retirer 25 % de la garantie (750 000 $ d'USDe), la vendre contre de l'USDC, puis rembourser 25 % de la dette (450 000 $). Il reste 300 000 $ en cash.

### 2.1 Le coût de sortie (certain)

Vendre n'est pas gratuit. Il y a trois composantes :

| Composante | Formule | Vente de 25 % d'aave_01 (750 000 $) |
|---|---|---|
| Frais de trading | taille × 0,1 % | 750 $ |
| Gas (frais de transaction blockchain) | fixe | 40 $ |
| **Impact de prix** | taille² / (profondeur + taille) | 750 000² / (300 M + 750 000) = **1 870,32 $** |
| **Total** | | **2 660,32 $** |

**Impact de prix :** quand on vend beaucoup d'un coup dans une pool, notre propre vente fait baisser le prix. Plus la pool est **profonde** (beaucoup de liquidité, ici 300 M$), moins on la fait bouger.

**Convexité :** l'impact croît plus vite que la taille. Vendre 2 fois plus coûte plus de 2 fois plus cher.

| Vente | 25 % | 50 % | 75 % | 100 % |
|---|---|---|---|---|
| Impact de prix | 1 870 $ | 7 463 $ | 16 749 $ | 29 703 $ |

La formule `taille² / (profondeur + taille)` est un **proxy** (une approximation). C'est le modèle d'une pool « produit constant » (type Uniswap v2). Les vraies pools de stablecoins (Curve) sont plus efficaces, donc le proxy **surestime** probablement le coût.

### 2.2 La perte résiduelle (si la crise arrive)

Ce qu'on n'a pas vendu reste exposé : **perte résiduelle = (1 − x) × 150 000 $**.
- Vendre 25 % laisse 112 500 $ de perte possible.
- Vendre 100 % laisse 0 $.

### 2.3 Le rendement perdu (certain)

Une position rapporte de l'argent tant qu'on la garde : c'est le **carry**. Si on vend, on y renonce. Le cash rapporte 0 % (convention du projet).

Pour aave_01 :
- la garantie rapporte 3 M$ × 5 % = 150 000 $/an ;
- la dette coûte 1,8 M$ × 5,5 % = 99 000 $/an ;
- le carry net vaut donc **51 000 $/an**, soit sur 7 jours 51 000 × 7/365 = **978,08 $**.

En vendant 25 %, on perd 25 % × 978,08 = **244,52 $**.

### 2.4 Le seuil de bascule p\*

On compare un **coût certain** à une **perte incertaine**. Sans connaître la probabilité de la crise, on peut au moins dire **à partir de quelle probabilité l'option devient rentable** :

```
p*(x) = (coût de sortie + rendement perdu) / (perte évitée)
```

Pour 25 % : p\* = (2 660,32 + 244,52) / 37 500 = **7,75 %**.

> Si tu penses que le depeg a **plus de 7,75 %** de chances d'arriver sur 7 jours, réduire de 25 % vaut le coup.

| Option | Coût certain | Perte évitée | p\* |
|---|---|---|---|
| 25 % | 2 905 $ | 37 500 $ | 7,75 % |
| 50 % | 9 492 $ | 75 000 $ | 12,66 % |
| 75 % | 19 773 $ | 112 500 $ | 17,58 % |
| 100 % | 33 721 $ | 150 000 $ | 22,48 % |

### 2.5 L'objectif J(x), quand on connaît la probabilité p

```
J(x) = coût de sortie + p × perte résiduelle + rendement perdu      → on prend le plus petit
```

**Exemple avec p = 10 % :**

| Vente | Coût certain | + p × perte restante | = J(x) |
|---|---|---|---|
| 0 % | 0 | 15 000 | 15 000 |
| **25 %** | 2 905 | 11 250 | **14 155** ← meilleur, donc REDUCE 25 % |
| 50 % | 9 492 | 7 500 | 16 992 |
| 100 % | 33 721 | 0 | 33 721 |

**Pourquoi la recommandation bouge avec p :** chaque tranche de 25 % vendue évite en moyenne p × 37 500 $. Mais chaque tranche coûte plus cher que la précédente (convexité) : 2 905, puis 6 587, puis 10 281, puis 13 948 $.
- p = 15 % : une tranche évite 5 625 $, donc seule la 1ʳᵉ est rentable. **REDUCE 25 %**.
- p = 40 % : une tranche évite 15 000 $, donc toutes sont rentables. **EXIT**.

**Piège :** p\* compare une option à « ne rien faire ». Il ne désigne pas la meilleure option : pour ça, il faut J(x).

### 2.6 Les règles de recommandation (section 8 du blueprint)

| Situation | Mode | Recommandation |
|---|---|---|
| Pas de probabilité fournie | `conditional_stress` | **INSUFFICIENT_DATA** + tableau + p\* (on n'invente pas de probabilité) |
| Probabilité + vrais prix | `expected_cost` | argmin J(x) : STAY / REDUCE / EXIT |
| Probabilité + prix approximatifs (proxy) | `expected_cost` | idem, mais avec le signal `proxy_quotes` |
| Aucun prix du tout | — | **INSUFFICIENT_DATA** |

Dans les fixtures actuelles, la probabilité vaut `null`. La sortie attendue pour aave_01 est donc **INSUFFICIENT_DATA**.

---

## 3. Ce qui a été fait, étape par étape

### Étape 0 : état des lieux (aucun code)

**Constats :**
- Toutes les données d'exemple existent dans `contracts/fixtures/demo_ethena_01/`. Inutile de les recopier depuis le blueprint.
- `decision_result.json` y donne **la sortie exacte attendue** pour aave_01. C'est notre **corrigé**, aussi appelé *golden fixture*.
- `contracts/` fait foi sur le blueprint en cas de différence.
- `decision.py` (premier jet écrit hors du repo) se trouvait dans `~/Downloads/`.

**4 problèmes repérés :**

| # | Problème | Statut |
|---|---|---|
| 1 | Le snapshot (P1) dit `executable_quote`, la sortie (P3) attend `executable`. Le code recopiait la valeur telle quelle | ✅ corrigé (1bis) |
| 2 | Le texte `reason` ne correspondait pas au corrigé, et l'option 25 % était codée en dur | ✅ corrigé (1bis) |
| 3 | 4 identifiants obligatoires manquaient (`decision_id`, `simulation_id`, `portfolio_id`, `scenario_id`) | ✅ corrigé (étape 2) |
| 4 | pytest n'était pas installé | ✅ installé (1bis) |

### Étape 1 : mise en place
- `decision.py` a été déplacé dans `backend/execution/`, et un `__init__.py` vide a été ajouté. Le dossier devient un **package** Python : P4 pourra écrire `from backend.execution.decision import ...`.
- Le script reproduit les **5 lignes du corrigé** (coût, rendement perdu, p\*).
- Commit `9f9e5dd`.

### Étape 1bis : correction des problèmes de l'étape 0

**`quote_status` honnête.** En creusant le problème 1, on a vu pire qu'une faute de vocabulaire : le code calculait **toujours** avec le proxy, mais affichait l'étiquette annoncée par P1. Si P1 avait écrit `executable_quote`, on aurait présenté un chiffre approximatif comme un prix réel. Le moteur aurait alors donné une recommandation « ferme », sans signal d'alerte.
→ Désormais, `quote_status` indique **la méthode réellement utilisée** (`proxy`). Un avertissement apparaît si la venue annonce une meilleure méthode.

**Texte `reason`.**
- Il est identique au corrigé : *« No scenario probability supplied and all quotes are proxies. Reducing by 25% beats staying if the user's probability of this depeg exceeds 7.75%. »*
- Il nomme l'option qui devient rentable **au p le plus bas**, au lieu de toujours prendre 25 %.
- Il adapte le nom du scénario (« depeg » ou « liquidity crisis »).

**pytest** : installé (version 9.1.1).

Commit `c50ac6c`.

### Étape 2 : lecture des vrais fichiers JSON

**`load_contracts(liquidity=False)`** charge les 4 fichiers d'entrée, en **lecture seule** :
- `portfolio.json`, `market_snapshot.json` ;
- `risk_result.json` + `scenario_request.json` (scénario depeg) ;
- ou les versions `_liquidity` avec `liquidity=True`.

**`decide_position(portfolio, snapshot, risk_result, scenario_request, position_id)`** :

| Ce qu'elle va chercher | Où | aave_01 |
|---|---|---|
| La position | `portfolio.json` | 3 M$ garantie, 1,8 M$ dette, venue `venue:usde_usdc` |
| La perte si crise | `risk_result.json` → `conditional_loss_usd` | 150 000 $ |
| L'horizon | `scenario_request.json` → `scenario.horizon_days` | 7 jours |
| La probabilité | `scenario_request.json` → `assumptions.probability` | `null` |
| `decision_id` | `"decision_"` + `request_id` | `decision_sim_001` |
| `simulation_id`, `portfolio_id`, `scenario_id` | recopiés | `result_sim_001`, `demo_ethena_01`, `usde_depeg` |

**Contrôles de cohérence.** Une erreur est levée si :
- `risk_result` et `scenario_request` n'ont pas le même `request_id`, `portfolio_id`, `scenario_id` ou `horizon_days` ;
- la position n'existe pas, ou sa perte manque. On n'invente jamais de valeur.

**Pourquoi ces contrôles ?** Mélanger la perte du scénario liquidité (142 857 $) avec la requête depeg donnerait un p\* faux : 2 905 / 35 714 = 8,13 % au lieu de 7,75 %. Le résultat serait étiqueté « depeg », et personne ne s'en apercevrait. Mieux vaut planter clairement que se tromper en silence.

**Résultat :** la sortie pour aave_01 est **identique au corrigé 11.8, champ par champ et dans le même ordre**.

Commit `eea69a3`, puis branche poussée sur GitHub (`origin/feat/p3`).

### Étape 3 : les 4 positions et le résumé du portefeuille

**Deux façons de « sortir »** (section 7.2) :

| Type | Sortir de x % | Exemple 25 % |
|---|---|---|
| Position simple (`token_holding`, `pt_holding`) | vendre x % des jetons | ethena_susde_01 : 400 000 sUSDe × 1,25 $ = 500 000 $ vendus |
| Position avec dette (`collateralized_borrow`) | retirer x % de la garantie, la vendre, rembourser x % de la dette | aave_01 : vendre 750 000 $ d'USDe, rembourser 450 000 $ d'USDC, garder 300 000 $ en cash |

Dans les deux cas, **le coût se calcule sur ce qu'on vend**, c'est-à-dire x × la valeur brute (et non la valeur nette). Rembourser de l'USDC avec de l'USDC ne coûte rien en impact de prix.

**Le ratio d'endettement ne bouge pas** quand on vend la même proportion de garantie et de dette. Pour aave_01, 1,8/3,0 = 0,6 avant, et 1,35/2,25 = 0,6 après une sortie de 25 %. La position devient juste plus petite.

**Résultats sur les 4 positions** (scénario depeg) :

| Position | Perte si crise | Coût sortie 25 % | Coût sortie 100 % | Rendement perdu (100 %, 7 j) | p\* 25 / 50 / 75 / 100 % |
|---|---|---|---|---|---|
| ethena_susde_01 | 100 000 | 1 787 | 21 842 | 2 685 | 9,8 / 14,7 / 19,6 / 24,5 % |
| aave_01 | 150 000 | 2 660 | 32 743 | 978 | 7,8 / 12,7 / 17,6 / 22,5 % |
| morpho_01 | 150 000 | 3 592 | 47 375 | **−2 110** | 8,2 / 15,5 / 22,9 / 30,2 % |
| pendle_01 | 123 321 | 3 646 | 50 823 | 3 452 | 14,6 / 24,5 / 34,3 / 44,0 % |

Comment lire ce tableau :
- Probabilité `null` dans les fixtures → les 4 positions sortent **INSUFFICIENT_DATA**. C'est normal et voulu.
- **pendle_01 est la plus chère à protéger** : sa pool est 4 fois moins profonde (80 M$ contre 300 M$), et il faut au moins 14,6 % de risque pour que la moindre vente vaille le coup.
- **aave_01 est la moins chère** : la pool USDe est la plus profonde.
- **morpho_01 a un rendement perdu négatif.** Sa garantie est notée à 0 % de rendement, alors qu'on paie 5,5 % sur la dette. Garder la position *coûte* donc 110 000 $/an : la vendre fait économiser des intérêts, d'où le signe moins. Ce n'est pas un coût négatif mais un gain. Voir le point d'attention n°4 plus bas.

**Exemple si l'utilisateur donnait p = 10 %** (démonstration, pas dans `contracts/`) :

| Position | Recommandation |
|---|---|
| ethena_susde_01 | REDUCE 25 % |
| aave_01 | REDUCE 25 % |
| morpho_01 | REDUCE 25 % |
| pendle_01 | STAY (10 % < 14,6 %) |

**Résumé du portefeuille (`portfolio_summary`)** : il additionne les choix position par position, sans chercher la meilleure combinaison globale (section 4.2).
- `stay_conditional_loss_usd` = 523 320,57 $ = perte totale si on ne fait rien. C'est le même chiffre que P2.
- `chosen_actions` = somme des coûts, rendements perdus et pertes restantes des options choisies. Il vaut `null` si une position est INSUFFICIENT_DATA : on n'additionne pas des choix qui n'existent pas. Avec p = 10 %, on obtient 8 039 $ de coûts pour faire passer la perte possible de 523 321 $ à 423 321 $.
- **Avertissement de venue partagée** : ethena_susde_01 et morpho_01 vendent tous les deux du sUSDe dans la même pool. Calculés séparément, leurs coûts **sous-estiment** une vente simultanée : la 2ᵉ vente arrive dans une pool déjà « creusée » par la 1ʳᵉ. Le résumé le signale.

**Ce résumé n'a pas de schéma dans `contracts/`.** C'est une sortie interne de P3, destinée à l'API et à P4. Si P4 veut l'utiliser, il faudra ajouter un schéma (P3 est propriétaire de `decision_result`) via une PR d'équipe.

Commit : voir l'historique plus bas.

---

## 4. Organisation du code actuel

```
backend/execution/
├── __init__.py              (vide : fait du dossier un package)
├── decision.py              moteur de décision
├── tests/
│   └── test_decision.py     tests pytest
├── README.md                (consignes d'origine, sera réécrit à l'étape 8)
└── JOURNAL_P3.md            ce fichier
```

**Fonctions de `decision.py` :**

| Fonction | Rôle |
|---|---|
| `usd(x)` / `ratio(x)` | Arrondi **à la sortie seulement** : 2 décimales pour les $, 4 pour les ratios |
| `price_impact(size, depth)` | Proxy produit constant : size² / (depth + size) |
| `annual_carry(position, yields)` | Rendement net annuel en $ (garantie × APY − dette × APY d'emprunt) |
| `option_label(x)` | « Reducing by 25% » / « Exiting fully » pour le texte `reason` |
| `decide(...)` | Le cœur du calcul : 5 options, coûts, p\*, J(x), recommandation |
| `load_contracts(...)` | Lit les fichiers JSON des contrats |
| `decide_position(...)` | **Point d'entrée** : contrats JSON → `decision_result` au format 11.8 |
| `portfolio_summary(...)` | Additionne les choix des positions et signale les venues partagées |
| `decide_portfolio(...)` | Décision des 4 positions + résumé |

**Règles respectées :**
- Tous les calculs sont en `Decimal` (pas de `float`), pour éviter les erreurs d'arrondi du type 0,1 + 0,2 = 0,30000000000000004.
- Les pertes et les coûts sont toujours positifs.
- Les nombres sont des chaînes de caractères dans le JSON (`"2660.32"`).
- Aucune dépendance lourde : seulement la bibliothèque standard, plus pytest pour les tests.
- Rien n'a été modifié dans `contracts/`.

---

## 5. Les tests

Lancer depuis la **racine du repo** :
```bash
python3 -m pytest backend/execution -v
```

| Test | Ce qu'il vérifie |
|---|---|
| `test_aave_01_matches_golden_fixture_field_by_field` | La sortie aave_01 est identique au corrigé 11.8 (champs, ordre, valeurs) |
| `test_inconsistent_request_ids_are_rejected` | Des fichiers d'entrée de simulations différentes sont refusés |
| `test_unknown_position_is_rejected` | Une position inconnue lève une erreur claire |
| `test_all_four_positions_get_five_options` | Les 4 positions ont bien leurs 5 options 0 à 100 % |
| `test_borrow_position_sells_collateral_not_net_equity` | Position avec dette : on paie les frais sur la garantie vendue (750 $), pas sur la valeur nette |
| `test_summary_stay_loss_matches_risk_result_total` | La perte totale « on ne fait rien » = total de P2 ; pas de total des choix sans probabilité |
| `test_summary_adds_chosen_actions_and_flags_shared_venue` | Avec p = 10 %, le total = somme des choix, et la venue partagée sUSDe est signalée |

Dernier résultat : **7 passed**.

On peut aussi lancer `python3 backend/execution/decision.py` : le script affiche « IDENTIQUE » puis le JSON complet.

---

## 6. Historique git (branche `feat/p3`)

```
(étape 3) P3: run decisions on all four positions + portfolio summary  ← étape 3
fdad924  P3: add step-by-step journal (steps 0-2)
eea69a3  P3: decide_position reads the real contract files      ← étape 2
c50ac6c  P3: honest quote_status and golden reason text           ← étape 1bis
9f9e5dd  P3: add initial decision engine to backend/execution     ← étape 1
9b72d0b  (main) Add link to BelemCapital hackathon PDF
```

`main` n'a pas été modifiée. Aucune pull request n'est ouverte.

---

## 7. Points d'attention à garder en tête

- **Branches des coéquipiers** : `feat/risk-engine` (P2) et `feat/frontend` (P4) existent, avec un « live risk engine ». À l'intégration, il faudra vérifier que leur `risk_result` a bien le format que P3 lit.
- **Perte manquante** : on lève une erreur pour l'instant. On pourra plus tard renvoyer un `INSUFFICIENT_DATA` propre si P4 préfère.
- **Le proxy surestime** probablement l'impact de prix sur les pools de stablecoins (Curve). C'est à signaler dans le README final.
- **Rendement de la garantie morpho_01 (à remonter à P1)** : le snapshot met `collateral_supply_apy = 0.00`, parce que Morpho ne verse pas d'intérêts sur la garantie. Mais la garantie est du **sUSDe**, dont la valeur en USDe monte d'elle-même d'environ 7 %/an (c'est le `token_apy` d'ethena_susde_01). Avec 0 %, le carry de morpho_01 vaut −110 000 $/an. En comptant les 7 %, il vaudrait environ +100 000 $/an (3 M$ × 7 % − 2 M$ × 5,5 %). Les p\* de morpho_01 seraient alors plus élevés. Proposition : que P1 ajoute ce rendement « intrinsèque » au snapshot. P3 n'y touche pas.

---

## 8. La suite

| Étape | Contenu |
|---|---|
| 4 | Estimateur de coût de sortie interchangeable (vrai prix → réserves de pool → proxy) |
| 5 | Règles de recommandation complètes ; vérification avec le scénario liquidité |
| 6 | Tests pytest complets (section 16 P3) |
| 7 | Données de sensibilité pour le curseur du dashboard |
| 8 | Point d'entrée pour l'API `POST /api/v1/decide` + README |
