# Journal P3 : ce qui a été fait jusqu'ici

> Module P3 : *Decision, Liquidity & Exit Optimization*
> Branche : `feat/p3` (poussée sur GitHub)
> État : les 8 étapes sont terminées

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

Commit `ff6fbc4`.

### Étape 4 : estimateur de coût de sortie interchangeable

**Pourquoi :** la qualité d'un prix de sortie dépend énormément de sa source. Le proxy est une formule de secours. Dès que P1 saura obtenir un vrai prix, il faut pouvoir le brancher **sans toucher au moteur de décision**.

**Les 3 sources, dans l'ordre de priorité** (section 7.2) :

| Rang | Source (`quote_status`) | Ce que c'est | Statut |
|---|---|---|---|
| 1 | `executable` | Un vrai devis : un agrégateur (1inch, CowSwap…) répond « pour 750 000 USDe je te donne exactement X USDC » | emplacement vide, pour P1 |
| 2 | `pool_reserves` | On lit l'état réel de la pool (réserves, courbe) et on calcule l'impact | emplacement vide, pour P1 |
| 3 | `proxy` | La formule taille² / (profondeur + taille) | implémentée |

Pour chaque taille de sortie (25 %, 50 %…), l'estimateur essaie les sources dans cet ordre et **prend la première qui répond**. Une même position peut donc avoir un vrai devis pour 25 % et le proxy pour 100 %. Ça arrive quand un agrégateur ne cote pas les très gros montants : chaque ligne affiche alors sa propre méthode.

**Comment P1 branchera un vrai prix :**
```python
def mon_devis(venue_id, venue, size_usd):
    ...                      # appel à l'agrégateur
    return impact_en_usd     # ou None si pas de devis pour cette taille

decide_position(..., estimator=ExitCostEstimator(executable=mon_devis))
```
La fonction renvoie **l'impact de prix seulement**. Les frais (0,1 %) et le gas (40 $) restent lus dans la venue.

**`quote_status` dit toujours la vérité** : c'est la méthode réellement utilisée. Si la venue annonce `executable_quote` mais qu'aucun devis n'a répondu, on affiche `proxy` et on ajoute un avertissement. La table `DECLARED_METHOD` traduit le vocabulaire de P1 (`executable_quote`) vers celui de P3 (`executable`).

**Aucun prix du tout** (venue absente, profondeur inconnue, frais inconnus) :
- recommandation **INSUFFICIENT_DATA**, mode `conditional_stress`, **même si une probabilité est fournie** ;
- on ne garde que la ligne 0 % (rien à vendre, coût 0), notée `unavailable` ;
- les autres lignes sont **retirées**, pas remplies avec des chiffres inventés. Le schéma de `decision_result` impose des nombres dans les champs de coût (pas de `null`) : retirer la ligne est la seule façon honnête de rester valide.

**Le golden aave_01 est toujours identique** : rien ne change tant que seul le proxy répond.

**Changement pratique :** `decision.py` importe maintenant `exit_cost.py`. On lance donc le script comme un module : `python3 -m backend.execution.decision`.

Commit `20d31e4`.

### Étape 5 : règles de recommandation complètes (section 8)

**Les 3 règles, telles qu'implémentées :**

| Situation | `mode` | `objective_usd` | Recommandation | Signal |
|---|---|---|---|---|
| Pas de probabilité | `conditional_stress` | `null` partout | INSUFFICIENT_DATA | — |
| Probabilité + vrais prix (`executable` / `pool_reserves`) | `expected_cost` | J(x) chiffré | argmin J(x) : STAY / REDUCE / EXIT | — |
| Probabilité + au moins un prix `proxy` | `expected_cost` | J(x) chiffré | argmin J(x), **affichée** | `proxy_quotes` dans `warnings` |
| Aucun prix du tout (étape 4) | `conditional_stress` | `null` | INSUFFICIENT_DATA | — |

Le schéma n'a pas de champ « flags » : le signal `proxy_quotes` est donc un avertissement qui **commence par** `proxy_quotes`. P4 peut le repérer facilement.

**Détails ajoutés :**
- **Égalité de J(x)** : on garde l'option qui vend le moins. À coût attendu égal, inutile de trader.
- **Probabilité invalide** (hors de 0 à 1) : erreur claire.
- **p\* négatif** : ça arriverait si une sortie *rapportait* plus qu'elle ne coûte, par exemple avec un carry très négatif. p\* est alors ramené à 0, ce qui veut dire « bat STAY quelle que soit la probabilité ». Une probabilité négative n'aurait pas de sens.

**Le texte `reason` cite toujours le meilleur seuil de bascule**, c'est-à-dire l'option qui bat STAY au p le plus bas, et le nom du scénario. Exemples sur aave_01 :
- sans p : *« No scenario probability supplied and all quotes are proxies. Reducing by 25% beats staying if the user's probability of this depeg exceeds 7.75%. »* (identique au corrigé) ;
- p = 15 % : *« With a 15% probability of this depeg, reducing by 25% has the lowest expected cost (19779.84 USD vs 22500.00 USD for staying). Reducing by 25% beats staying if … exceeds 7.75%. Exit costs are proxy estimates. »*

**Pourquoi le meilleur seuil est presque toujours à 25 %.** L'impact de prix est convexe : petite vente, petit coût par dollar protégé. Mais si le **coût fixe** (le gas) domine, c'est l'inverse : on paie les 40 $ (ou 5 000 $) une seule fois, qu'on vende 25 % ou 100 %. Dans ce cas, mieux vaut vendre gros. Le test `test_reason_names_the_cheapest_threshold_not_always_25pct` le montre avec une pool quasi infinie et 5 000 $ de gas : la sortie totale devient rentable avant la sortie de 25 %.

**Scénario liquidité (`risk_result_liquidity.json`)** pour aave_01 :

| | Depeg | Crise de liquidité |
|---|---|---|
| Perte si crise | 150 000 $ | 142 857 $ |
| Coût sortie 25 % | 2 660,32 $ | **2 660,32 $** (identique) |
| p\* 25 % | 7,75 % | 8,13 % |
| p\* 100 % | 22,48 % | 23,60 % |

Le coût est **identique** parce qu'on sort **avant** la crise, avec la profondeur normale de 300 M$, et non avec les 60 M$ de crise. Le moteur lit la profondeur dans le snapshot et n'applique jamais `exit_liquidity_reduction_pct`. Seule la perte évitée change.

**Limite repérée (à discuter, non corrigée car le blueprint fait foi) :** dans la crise de liquidité, la perte est un coût de vente forcée, et ce coût est convexe. Le blueprint dit perte résiduelle = (1 − x) × perte, une règle proportionnelle. Mais si on garde 75 % d'aave_01 et qu'on doit le vendre pendant la crise, le vrai coût serait 2,25 M² / (60 M + 2,25 M) = **81 325 $**, pas 0,75 × 142 857 = **107 143 $**. La règle proportionnelle **surestime** donc le risque restant, ce qui pousse à sortir un peu trop.

Commit `f98ae3f`.

### Étape 6 : tests exigés par la section 16

Le fichier `tests/test_section16.py` contient un test par exigence du blueprint. Ces tests vérifient des **propriétés financières**, pas seulement des chiffres : si quelqu'un modifie le moteur et casse le bon sens économique, un test échoue. Les tests marqués « × 4 » tournent sur les 4 positions (`pytest.mark.parametrize`).

| Test | En une ligne |
|---|---|
| `test_zero_exit_costs_nothing` (× 4) | Ne rien vendre coûte 0 : ni frais, ni gas, ni impact, ni rendement perdu |
| `test_exit_cost_is_convex_in_size` (× 4) | Vendre 2× plus coûte plus de 2× plus en impact, et chaque tranche de 25 % coûte plus que la précédente |
| `test_full_exit_leaves_no_residual_loss` | Tout vendre ne laisse aucune perte possible ; à p = 40 %, c'est EXIT |
| `test_no_incident_means_stay` | Si le scénario ne fait rien perdre, on reste (STAY) : vendre ne ferait que coûter |
| `test_higher_probability_never_lowers_the_exit` (× 4) | En faisant monter p de 0 à 100 %, la part vendue ne baisse jamais ; p = 0 → STAY, p = 1 → EXIT |
| `test_more_slippage_never_raises_the_exit` (× 4) | En rendant la pool de plus en plus mince (profondeur × 10 → × 0,1), la part vendue ne monte jamais, et elle change vraiment |
| `test_partial_exit_can_win` | À p = 15 %, vendre 25 % bat à la fois « garder tout » et « tout vendre » |
| `test_golden_values_section_11_8` | Les 5 lignes du corrigé (coût, rendement perdu, p\*) et INSUFFICIENT_DATA sans probabilité |

**Pourquoi la monotonie est garantie (intuition).** Augmenter p rend chaque tranche vendue plus précieuse (elle évite p × 37 500 $), sans changer son coût. On ne peut donc que vendre plus. À l'inverse, une pool plus mince rend chaque tranche plus chère, sans changer ce qu'elle évite : on ne peut que vendre moins. C'est le raisonnement par tranches de la question de l'étape 1.

**Résultat :** 20 tests dans ce fichier, **37 au total**, tous verts.

Commit `57b39ed`.

### Étape 7 : données de sensibilité pour le dashboard

**Pourquoi :** nos chiffres reposent sur deux hypothèses fragiles, la probabilité de la crise et la profondeur des pools. Le gestionnaire doit voir **à quel point la décision en dépend**. P4 affichera un curseur. `sensitivity()` (dans `sensitivity.py`) lui prépare toutes les valeurs à l'avance, dans un JSON simple, pour qu'il n'ait aucun calcul à faire.

**1. J(x) en fonction de p** (`objective_vs_probability`) : 51 points de 0 à 50 % pour chacune des 5 options, plus la meilleure option à chaque point. Pour aave_01 :

| p | J(0 %) | J(25 %) | J(50 %) | J(75 %) | J(100 %) | Meilleur |
|---|---|---|---|---|---|---|
| 0 % | 0 | 2 905 | 9 492 | 19 773 | 33 721 | 0 % (STAY) |
| 10 % | 15 000 | **14 155** | 16 992 | 23 523 | 33 721 | 25 % |
| 20 % | 30 000 | 25 405 | **24 492** | 27 273 | 33 721 | 50 % |
| 30 % | 45 000 | 36 655 | 31 992 | **31 023** | 33 721 | 75 % |
| 50 % | 75 000 | 59 155 | 46 992 | 38 523 | **33 721** | 100 % (EXIT) |

Comment lire le graphique que P4 en tirera :
- **chaque option est une droite** : J(x) = coût certain + p × perte restante ;
- **elle part du coût certain** (à p = 0) ;
- **sa pente vaut la perte restante**. La droite « tout vendre » est donc **plate** : il ne reste rien d'exposé.
- La meilleure option est la droite la plus basse. Quand p augmente, on passe d'une droite à la suivante : 0 → 25 → 50 → 75 → 100 %.

**2. p\* quand la pool est plus mince** (`break_even_vs_depth`), pour aave_01 :

| Profondeur | p\* 25 % | p\* 50 % | p\* 75 % | p\* 100 % |
|---|---|---|---|---|
| 300 M$ (÷ 1) | 7,75 % | 12,66 % | 17,58 % | 22,48 % |
| 150 M$ (÷ 2) | 12,71 % | 22,51 % | 32,24 % | 41,89 % |
| 60 M$ (÷ 5) | 27,45 % | 51,49 % | 74,98 % | 97,92 % |
| 30 M$ (÷ 10) | 51,54 % | 97,94 % | **142,22 %** | **184,50 %** |

**Un p\* au-dessus de 100 %** veut dire que la sortie coûte plus cher que **toute** la perte qu'elle évite : même une crise certaine ne la justifierait pas. Le chiffre est gardé, parce qu'il est vrai et montre l'ampleur du problème. Mais le texte `reason` du moteur a été corrigé : il disait « beats staying if probability exceeds 184% », ce qui n'avait pas de sens. Il dit maintenant *« no exit can beat staying even if this depeg is certain »*.

**À retenir :** la recommandation pour aave_01 est **très sensible à la profondeur**. Si la vraie pool n'avait que 60 M$ de liquidité, il faudrait plus de 27 % de risque pour justifier ne serait-ce qu'une réduction de 25 %. D'où l'importance que P1 fournisse de vrais devis.

**Garde-fous :**
- Le premier avertissement est toujours *« Assumption-driven: probabilities are user inputs… »* (section 7.4).
- Diviser la profondeur ne fait bouger **que le proxy**. Si un vrai devis est branché, un avertissement le signale.
- Profondeur inconnue : les p\* sont vides et un avertissement explique pourquoi.

Commit `a399922`.

### Étape 8 : point d'entrée pour P4 et README

**Le point d'entrée (`entrypoint.py`).** P4 construit l'API web. Il n'a qu'à brancher **une seule fonction**, `handle_decide_request(request)`, sur `POST /api/v1/decide`, en 3 lignes de FastAPI (l'exemple est dans le README). La fonction **ne plante jamais** : elle renvoie toujours un code HTTP et une réponse JSON.

**Ce que P4 envoie** (exemple) :
```json
{ "schema_version": "1.0", "portfolio_id": "demo_ethena_01", "position_id": "aave_01",
  "scenario_id": "usde_depeg", "probability": "0.15" }
```
- `probability` est la valeur du **curseur du dashboard**. Elle vient de l'utilisateur, jamais de nous. Sans ce champ, on prend celle de `scenario_request` (`null` dans les fixtures).
- `include` (optionnel) : `"sensitivity"` et/ou `"portfolio_summary"` pour recevoir en plus les données de l'étape 7 et le résumé de l'étape 3.
- `inputs` (optionnel) : les vrais JSON de P1/P2. C'est le **mode live**. Sans `inputs`, on charge les fixtures, c'est le **mode fixture**. Le README de l'API demande ce double mode pour que la démo marche dès le premier jour.

**Ce que P3 renvoie :**
- **200** : `{"status": "ok", "mode": "fixture", "decision": {...}}`. Avec p = 15 % pour aave_01, on obtient REDUCE 25 %. Sans probabilité, on obtient exactement le corrigé 11.8.
- **Erreur** : `{"status": "error", "error": {"code": ..., "message": ...}}`, avec un code HTTP adapté :

| HTTP | Code | Quand |
|---|---|---|
| 400 | `unsupported_schema_version` | Mauvaise version de schéma |
| 404 | `unknown_portfolio` / `unknown_position` | Portefeuille ou position inconnus |
| 422 | `invalid_request` | Champ manquant, scénario inconnu, probabilité qui n'est pas une chaîne décimale… |
| 422 | `invalid_inputs` | Données incohérentes (ids, horizon), probabilité hors de 0 à 1 |

**Pourquoi refuser `0.15` (nombre) et exiger `"0.15"` (chaîne) ?** En informatique, 0.15 écrit comme un nombre à virgule n'est pas exactement 0,15 mais 0,1499999999999999944… C'est pour ça que toute l'équipe a convenu de transmettre les nombres en chaînes. Le message d'erreur le dit clairement.

**Le README.** Le contenu d'origine (les consignes) est **gardé tel quel**. La documentation a été **ajoutée en bas**, en anglais comme les autres README, pour l'équipe : organisation du module, format de requête et de réponse, erreurs, formules en une ligne, règles de recommandation, comment P1 branche un vrai prix, hypothèses, limites, points ouverts et lancement des tests.

**Les limites documentées :**
- le proxy **surestime** l'impact de prix sur les pools de stablecoins ;
- la sortie de sUSDe **n'est pas instantanée** : convertir du sUSDe en USDe chez Ethena impose une période d'attente (« cooldown »). Une sortie rapide dépend donc de la liquidité de la pool de marché, et c'est elle que le modèle chiffre ;
- les venues partagées sont chiffrées séparément ;
- la perte résiduelle proportionnelle surestime le risque en crise de liquidité ;
- les lignes sans prix sont retirées.

---

## 4. Organisation du code actuel

```
backend/execution/
├── __init__.py              (vide : fait du dossier un package)
├── entrypoint.py            point d'entrée unique pour POST /api/v1/decide (P4)
├── decision.py              moteur de décision
├── exit_cost.py             estimateur de coût de sortie (sources de prix interchangeables)
├── sensitivity.py           données de sensibilité pour le curseur de P4
├── tests/
│   ├── test_decision.py     tests du moteur
│   ├── test_exit_cost.py    tests de l'estimateur
│   ├── test_section16.py    tests exigés par la section 16
│   ├── test_sensitivity.py  tests des données de sensibilité
│   └── test_entrypoint.py   tests du point d'entrée
├── README.md                consignes d'origine + documentation du module (en bas, pour l'équipe)
└── JOURNAL_P3.md            ce fichier
```

**Fonctions de `decision.py` :**

| Fonction | Rôle |
|---|---|
| `usd(x)` / `ratio(x)` | Arrondi **à la sortie seulement** : 2 décimales pour les $, 4 pour les ratios |
| `annual_carry(position, yields)` | Rendement net annuel en $ (garantie × APY − dette × APY d'emprunt) |
| `option_label(x)` | « Reducing by 25% » / « Exiting fully » pour le texte `reason` |
| `decide(...)` | Le cœur du calcul : 5 options, coûts, p\*, J(x), recommandation |
| `load_contracts(...)` | Lit les fichiers JSON des contrats |
| `decide_position(...)` | **Point d'entrée** : contrats JSON → `decision_result` au format 11.8 |
| `portfolio_summary(...)` | Additionne les choix des positions et signale les venues partagées |
| `decide_portfolio(...)` | Décision des 4 positions + résumé |

**Contenu de `exit_cost.py` :**

| Élément | Rôle |
|---|---|
| `proxy_impact(venue_id, venue, size)` | Source proxy : size² / (depth + size), ou None si la profondeur est inconnue |
| `ExitQuote` | Un devis : frais, gas, impact de prix, `quote_status`, et `total_usd` |
| `ExitCostEstimator` | Essaie executable → pool_reserves → proxy et renvoie le premier devis, ou None |
| `DEFAULT_ESTIMATOR` | L'estimateur par défaut (proxy seul) |
| `DECLARED_METHOD` | Traduction du vocabulaire P1 (`executable_quote`) → P3 (`executable`) |

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

| `test_priority_executable_then_pool_then_proxy` | L'ordre de priorité des sources est respecté ; le proxy redonne 1 870,32 $ et 2 660,32 $ |
| `test_source_without_price_for_a_size_falls_back_per_size` | Un devis limité à 1 M$ sert pour 25 % ; au-delà, on retombe sur le proxy, ligne par ligne |
| `test_plugged_executable_quote_removes_proxy_flags` | Avec un vrai devis branché : `executable` partout, mode `expected_cost`, plus d'alerte proxy |
| `test_no_price_at_all_gives_insufficient_data` | Profondeur inconnue → INSUFFICIENT_DATA même avec p = 40 %, seule la ligne 0 % reste |
| `test_missing_venue_gives_insufficient_data` | Venue absente du snapshot → INSUFFICIENT_DATA |
| `test_venue_claiming_better_method_than_used_is_flagged` | La venue annonce `executable_quote` mais seul le proxy répond → `proxy` + avertissement |

| `test_probability_with_proxy_quotes_recommends_but_flags` | p = 15 % + proxy → `expected_cost`, REDUCE 25 %, J(x) chiffrés, signal `proxy_quotes` |
| `test_probability_outside_0_1_is_rejected` | Une probabilité de 1,5 est refusée |
| `test_reason_names_the_cheapest_threshold_not_always_25pct` | Gas énorme + pool infinie → le texte cite « Exiting fully », pas 25 % |
| `test_liquidity_crisis_exits_at_pre_crisis_depth` | Scénario liquidité : bons identifiants, coûts identiques au depeg (profondeur d'avant crise), p\* 25 % = 8,13 % |

Plus les 20 tests de `tests/test_section16.py`, détaillés dans la section « Étape 6 » ci-dessus, et ceux de `tests/test_sensitivity.py` :

| Test | Ce qu'il vérifie |
|---|---|
| `test_objective_curve_covers_0_to_50pct_for_every_option` | 51 points de 0 à 50 %, pour les 5 options |
| `test_objective_at_p0_is_the_certain_cost_and_full_exit_is_flat` | À p = 0, J = coût certain (2 904,84 $) ; la droite « tout vendre » est plate |
| `test_best_fraction_matches_the_engine_and_never_decreases` | À 15 %, meilleur = 25 % (comme le moteur) ; le meilleur choix ne recule jamais quand p monte |
| `test_break_even_rises_as_depth_is_divided` | p\* à ÷ 1 = golden 7,75 % ; tous les p\* montent quand la pool s'amincit |
| `test_missing_depth_gives_null_thresholds_and_a_warning` | Profondeur inconnue → pas de p\*, pas de choix, avertissement |
| `test_output_is_plain_json_with_string_numbers` | La sortie est du JSON pur, avec l'avertissement « Assumption-driven » en tête |
| `test_reason_says_no_exit_pays_when_every_p_star_exceeds_100pct` | Pool minuscule → tous les p\* > 100 %, et le texte dit qu'aucune sortie ne paie |

Et ceux de `tests/test_entrypoint.py` (étape 8) :

| Test | Ce qu'il vérifie |
|---|---|
| `test_fixture_mode_returns_the_golden_decision` | Sans probabilité, l'API renvoie exactement le corrigé 11.8 |
| `test_user_probability_drives_the_recommendation` | `probability: "0.15"` → `expected_cost`, REDUCE |
| `test_liquidity_scenario_and_optional_blocks` | Scénario liquidité + sensibilité + résumé du portefeuille dans la même réponse |
| `test_live_mode_uses_the_inputs_sent_by_p4` | En mode live, on utilise bien les données envoyées (perte doublée → 300 000 $) |
| `test_bad_requests_get_a_clear_error_not_a_crash` (× 10) | Chaque mauvaise requête donne le bon code HTTP, le bon code d'erreur et un message |
| `test_non_object_body_is_rejected` | Un corps qui n'est pas un objet JSON est refusé proprement |

Dernier résultat : **59 passed**.

On peut aussi lancer `python3 -m backend.execution.decision` depuis la racine : le script affiche « IDENTIQUE » puis le JSON complet.

---

## 6. Historique git (branche `feat/p3`)

```
(étape 8) P3: entry point for POST /api/v1/decide + README  ← étape 8
a399922  P3: sensitivity data for the dashboard slider  ← étape 7
57b39ed  P3: section 16 test suite  ← étape 6
f98ae3f  P3: complete section 8 recommendation rules + liquidity check  ← étape 5
20d31e4  P3: pluggable exit cost estimator (executable → pool → proxy)  ← étape 4
ff6fbc4  P3: run decisions on all four positions + portfolio summary  ← étape 3
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
- **Schéma `decision_result` (P3 en est propriétaire)** : les champs de coût (`fees_usd`, `price_impact_usd`…) ne peuvent pas valoir `null`. Quand une taille n'a pas de prix, on doit donc retirer la ligne. Proposition pour une PR d'équipe : autoriser `null` sur ces champs quand `quote_status = "unavailable"`, pour que P4 puisse afficher « pas de prix » au lieu d'une ligne manquante. C'est un changement additif, compatible v1.
- **Perte résiduelle en crise de liquidité** : la règle proportionnelle du blueprint surestime le risque restant (81 325 $ réels contre 107 143 $ pour aave_01 à 75 % gardé). À proposer à P2 et à l'équipe : recalculer la perte de vente forcée sur la taille restante (1 − x) au lieu de la proportionner. C'est P2 qui fournit la perte, et le blueprint fait foi.
- **No incident sans probabilité** : si la perte vaut 0, aucune sortie ne peut battre STAY, quelle que soit la probabilité. La règle 1 impose quand même INSUFFICIENT_DATA ; le texte `reason` dit alors « no exit can beat staying ». On pourrait renvoyer STAY directement, puisque ce n'est pas une probabilité inventée mais une dominance. C'est à trancher en équipe.

---

## 8. La suite

Les 8 étapes sont terminées. Ce qui reste relève de l'intégration avec l'équipe :

| Qui | Action |
|---|---|
| P4 | Brancher `handle_decide_request` sur `POST /api/v1/decide` (3 lignes, exemple dans le README) |
| P1 | Brancher un vrai devis via `ExitCostEstimator(executable=...)` ; corriger le rendement de la garantie morpho_01 |
| P2 | Vérifier que le `risk_result` de `feat/risk-engine` a le format lu par P3 ; discuter la perte résiduelle en crise de liquidité |
| Équipe | Trancher les points ouverts (schéma nullable, STAY par dominance) ; ouvrir la PR `feat/p3` → `main` |
