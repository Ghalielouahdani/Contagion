# P3 — Le moteur de décision : ce qu'il reçoit, ce qu'il fait, ce qu'on attend de lui

> Le détail technique (formules, codes d'erreur, tests) est dans [README.md](README.md). Ce document explique le concept, avec un exemple réel chiffré.

## En une phrase

Pour une position et un scénario de stress, P3 répond à la question du gérant : **« Est-ce que je garde, je réduis ou je sors, et est-ce que ça vaut ce que ça coûte ? »**

Il ne prédit pas si le scénario va arriver. Il compare, en dollars, le coût certain d'agir maintenant et la perte évitée **si** le scénario arrive. Puis il donne la probabilité à partir de laquelle agir devient rentable.

## Où il se place dans la chaîne

```
P1 découverte ──► P2 moteur de risque ──► P3 décision ──► dashboard
graphe + marchés    « que perd la position    « que faire, et à
réels (on-chain)     si le choc arrive ? »     partir de quand ? »
```

P3 ne recalcule pas les pertes. Il **consomme** le résultat de P2 pour la position, et les conditions de sortie (liquidité, frais, gas) du snapshot de marché de P1.

## Ce qu'il reçoit

| Entrée | D'où elle vient | Ce que P3 en utilise |
|---|---|---|
| `portfolio` | portefeuille (fictif sur marchés réels) | la position : collatéral, dette, venue de sortie |
| `market_snapshot` | P1 (on-chain) | courbe de cotations de la venue de sortie, frais, gas, rendements (carry), liquidité disponible d'un marché de prêt |
| `risk_result` | P2 | la **perte conditionnelle** de la position dans le scénario, et ses valeurs avant le choc |
| `scenario_request` | l'utilisateur (curseurs) | l'horizon en jours, et la **probabilité** du scénario si l'utilisateur en donne une |
| `position_id` | l'utilisateur | la position à décider |

Via l'API : `POST /api/v1/decide?set=<jeu>` avec `{"simulation_id": "<id renvoyé par /simulate>", "position_id": "morpho_01"}`. On peut aussi passer `{"request": <scenario_request>, "position_id": ...}` directement.

## Le concept

Pour chaque fraction de sortie x ∈ {0 %, 25 %, 50 %, 75 %, 100 %}, P3 calcule quatre montants sur le même horizon :

| Montant | Question | Calcul |
|---|---|---|
| **Coût de sortie** | Combien coûte de vendre maintenant ? | frais + gas + impact de prix (sur la vraie courbe de cotations quand elle existe) |
| **Perte résiduelle** | Que perd-on encore si le choc arrive ? | (1 − x) × perte conditionnelle de P2 |
| **Rendement perdu** | Que rapportait ce qu'on vend ? | x × (rendement − coût d'emprunt) × horizon |
| **Seuil de rentabilité p\*** | À partir de quelle probabilité agir paie ? | (coût + rendement perdu) / perte évitée |

**Sans probabilité**, P3 répond `INSUFFICIENT_DATA` : il ne force aucun trade, mais il donne le tableau et chaque seuil p\*. « Réduire de 25 % est rentable si vous croyez au scénario à plus de X % » : la décision reste au gérant.

**Avec une probabilité p**, il minimise le coût total attendu J(x) = coût + p × perte résiduelle + rendement perdu. La recommandation est STAY si x = 0, REDUCE si 0 < x < 1, EXIT si x = 1.

Principes :
- **jamais de probabilité inventée** : elle vient toujours de l'utilisateur ;
- **on sort avant le choc**, aux prix et à la liquidité d'aujourd'hui ;
- **une position empruntée se dénoue au prorata** : on vend x du collatéral et on rembourse x de la dette ;
- **un prêteur sort en retirant** de la liquidité inutilisée du marché. Au-delà, son argent est bloqué : c'est un délai, pas une perte.

## Exemple réel : un emprunteur Morpho trop proche du seuil

**La situation dans la vraie vie** (jeu `stress_portfolio_01`, position `morpho_01`) :
- 400 000 sUSDe déposés en collatéral sur le **vrai** marché Morpho sUSDe/PYUSD (109 M$, vérifié on-chain), soit 500 745 $ ;
- 440 626 PYUSD empruntés contre ce collatéral, soit 440 656 $ au prix observé du PYUSD ;
- LTV **0,880**, pour un seuil de liquidation (LLTV) de **0,915** : la position n'est qu'à 3,8 % de la liquidation ;
- l'oracle du marché lit le flux Chainlink **USDe/USD** : il voit donc un depeg de l'USDe, contrairement à celui d'Aave.

**Le scénario** : l'USDe perd 5 % sur le marché, sur un horizon de 7 jours.

**Ce que la position perd (P2)** :

| | Avant | Après le choc |
|---|---|---|
| Valeur du collatéral | 500 745 $ | 475 708 $ |
| Dette | 440 656 $ | 440 656 $ |
| LTV | 0,880 | **0,926 → liquidable** |
| Capital (net) | 60 090 $ | 23 507 $ |

Perte : **36 582 $, soit 61 % du capital de la position pour un depeg de 5 %**. La perte se décompose en 25 037 $ de baisse du collatéral et **11 545 $ de pénalité de liquidation** : les liquidateurs remboursent la dette et prennent 2,62 % en plus, et Morpho n'a pas de plafond de liquidation. C'est l'effet de levier : 5 % de baisse sur le collatéral, 61 % sur le capital.

**Ce que P3 propose** (vraies cotations de sortie) :

| Sortie | Coût de sortie | Rendement perdu (7 j) | Perte si le choc arrive | Seuil p\* |
|---|---|---|---|---|
| 0 % (garder) | 0 $ | 0 $ | 36 582 $ | — |
| 25 % | 87 $ | 28 $ | 27 437 $ | ≈ 1,25 % |
| 50 % | 118 $ | 56 $ | 18 291 $ | ≈ 0,96 % |
| 100 % | 246 $ | 113 $ | 0 $ | ≈ 0,98 % |

**Le verdict** :
- **sans probabilité** : `INSUFFICIENT_DATA`, avec l'information utile : sortir coûte environ 246 $ pour éviter 36 582 $ ;
- **à 5 %** ou **à 30 %** de probabilité : `EXIT 100 %`. Le coût attendu de garder est 0,05 × 36 582 = 1 829 $ (resp. 10 975 $), contre environ 360 $ pour sortir.

**La lecture pour le gérant** : avec un LTV de 0,88 sur un collatéral dont l'oracle suit l'USDe, se désendetter est rentable dès qu'on croit à un depeg de 5 % avec **plus d'environ 1 % de chances** sur la semaine. Ne rien faire, c'est accepter de perdre 61 % du capital de la ligne pour un mouvement de prix modeste.

### Le rendement du collatéral est compté

Morpho ne verse rien sur le collatéral (`collateral_supply_apy = 0`), mais le sUSDe déposé continue de rapporter son propre rendement à travers son taux de change (4,85 % par an, observé on-chain). Le snapshot le porte dans `asset_yields`, et `collateral_yield_apy` (backend/risk/pricing.py) l'ajoute au portage. Sortir fait donc renoncer à environ 113 $ sur 7 jours, d'où les seuils d'environ 1 % ci-dessus. Avant cette correction, le rendement perdu était négatif (−353 $) et tous les seuils à 0 % : sortir semblait faire gagner de l'argent.

## Ce qui est attendu en sortie

Un `decision_result` (schéma v1, `contracts/schemas/v1/decision_result.schema.json`) :
- **cinq options**, de 0 % à 100 %, chacune avec frais, gas, impact de prix, coût total, rendement perdu, perte résiduelle, seuil p\*, J (si une probabilité est donnée) et la source du prix (`executable`, `pool_reserves`, `proxy` ou `unavailable`) ;
- une **recommandation** : STAY, REDUCE, EXIT ou INSUFFICIENT_DATA, avec la fraction recommandée ;
- une **raison** en clair, qui cite toujours le meilleur seuil ;
- des **avertissements** : prix extrapolés au-delà des cotations, sortie limitée par la liquidité d'un marché de prêt, coûts estimés plutôt que cotés.

Garanties vérifiées par les tests :
- la fixture de décision de référence (section 11.8 du blueprint) est reproduite au centime ;
- **une probabilité n'est jamais inventée** ;
- une option sans prix est retirée plutôt que remplie avec un chiffre inventé ;
- la décision porte exactement sur le résultat de risque de la simulation demandée (`simulation_id`).

## L'essayer

```bash
.venv/bin/uvicorn backend.api.main:app --port 8000
S=http://localhost:8000/api/v1; SET=stress_portfolio_01; H='content-type: application/json'
SIM=$(curl -s -X POST "$S/simulate?set=$SET" -H "$H" --data @contracts/fixtures/$SET/scenario_request.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["simulation_id"])')
curl -s -X POST "$S/decide?set=$SET" -H "$H" -d "{\"simulation_id\": \"$SIM\", \"position_id\": \"morpho_01\"}" | python3 -m json.tool | head -40
```

Dans le dashboard : vue **Decision Engine**, après avoir lancé un scénario.

## Mode crise : le vrai verdict, sans probabilité

Le mode « prévention » ci-dessus répond par des seuils de probabilité, et sans probabilité il dit `INSUFFICIENT_DATA`. Le **mode crise** (`crisis.py`, Hamza) pose la question du gérant en pleine crise : **« le scénario arrive, que fait-on de chaque position pour perdre le moins ? »**

- **Les actions comparées** : garder, vendre 25 à 100 %, se désendetter jusqu'au seuil de sécurité, retirer (prêteurs). Réagir **avant** le mouvement (la perte de prix est évitable) ou **après** (seule la pénalité de liquidation l'est encore).
- **Le verdict** : la combinaison qui perd le moins (`min_loss`), avec les ventes sur une même venue chiffrées ensemble. C'est ce qu'affiche la page **Decision** du dashboard, à côté des autres stratégies (tout garder, tout vendre, seulement éviter les liquidations).

Exemple, portefeuille de stress, depeg −5 % : garder tout coûte **127 515 $** ; le verdict du moteur ramène la perte à **13 681 $** en agissant avant le mouvement.

## L'analyste IA (Gemini) : évaluation, 11 octobre 2026

Fonctionnement : le moteur calcule, l'IA explique et compose trois stratégies à partir des seules actions disponibles. Chaque stratégie de l'IA est **recalculée par le moteur**, et les chiffres de son texte sont confrontés aux données.

Évaluation sur le portefeuille de stress, scénarios A, C, D et G, avec le vrai modèle :

| Critère | Constat |
|---|---|
| Chiffres inventés | **Aucun** : les garde-fous fonctionnent (`ungrounded_numbers` vide) |
| Temps de réponse | 5 à 10 s, sans bloquer le verdict du moteur (0,02 s) |
| Stratégie recommandée | Le plus souvent, **la même que le verdict du moteur**. Une fois (crise combinée), une stratégie qui perdait **27 443 $ de plus**, sans justification chiffrée. Variable d'une exécution à l'autre. |
| Explication (avant correction) | Générique, sans le mécanisme de perte : l'IA ne recevait ni la décomposition des pertes ni la cascade |
| Stratégies « après le mouvement » (avant correction) | Totaux **non comparables** aux stratégies « avant » : ils excluaient la perte déjà subie. Une réaction tardive dans la cascade affichait 390 $, alors qu'elle coûte en réalité 1,34 M$ |
| Contradictions | Parfois « ce prêteur ne peut pas sortir » alors que le plan propose un retrait. C'est détecté et signalé |

Corrections faites :
- l'IA reçoit maintenant les composantes de perte de chaque position, la cascade et les exécutions de référence, et doit nommer les positions les plus touchées et leur canal. Ses explications sont devenues spécifiques au portefeuille (bad debt des prêteurs, boucle de liquidation) ;
- chaque stratégie tardive porte `total_including_incurred_usd`, et le dashboard compare toujours sur cette base.
- l'appel est déterministe (température 0, graine fixe) : deux exécutions sur le même plan donnent la même recommandation et les mêmes stratégies.

**Conclusion** : le verdict reste celui du moteur, déterministe et vérifiable. L'IA apporte une explication lisible et des alternatives chiffrées, mais elle n'est **pas fiable comme décideur**. Le dashboard affiche donc « l'analyste perd X $ de plus que le verdict : le verdict reste » quand elle s'en écarte.

## Limites restantes

- **Distribution des emprunteurs Aave** : la cascade utilise la vraie distribution des LTV pour les marchés Morpho (sUSDe/PYUSD, USDe/RLUSD), mais pas pour Aave, où il faudrait un indexeur des comptes de l'e-mode. Pour Aave, seule notre propre position est liquidée.
- **Jeu `live_ethena_01`** : la cassette de découverte n'enregistre pas encore les LTV des emprunteurs ; la cascade y reste limitée aux positions du portefeuille.
- **Au-delà des tailles cotées**, le coût de sortie est extrapolé et signalé comme tel. Le routeur Pendle ne trouve plus de route au-delà d'environ 4 M$ pour le PT-sUSDe.
