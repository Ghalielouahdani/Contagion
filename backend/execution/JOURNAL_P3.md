# Journal P3 : ce qui a été fait jusqu'ici

> Module P3 : *Decision, Liquidity & Exit Optimization*
> Branche : `feat/p3` (poussée sur GitHub)
> État : étapes 0, 1, 1bis et 2 terminées sur 8

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

Dernier résultat : **3 passed**.

On peut aussi lancer `python3 backend/execution/decision.py` : le script affiche « IDENTIQUE » puis le JSON complet.

---

## 6. Historique git (branche `feat/p3`)

```
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

---

## 8. La suite

| Étape | Contenu |
|---|---|
| 3 | Faire tourner les 4 positions ; différence token/PT et position avec dette ; résumé du portefeuille |
| 4 | Estimateur de coût de sortie interchangeable (vrai prix → réserves de pool → proxy) |
| 5 | Règles de recommandation complètes ; vérification avec le scénario liquidité |
| 6 | Tests pytest complets (section 16 P3) |
| 7 | Données de sensibilité pour le curseur du dashboard |
| 8 | Point d'entrée pour l'API `POST /api/v1/decide` + README |
