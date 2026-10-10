# Agent de scénarios de Risk

L'agent Gemini est accessible dans le chatbot depuis **Portfolio, Dependency Graph, Scenario Lab et Risk Engine**. Les nouvelles cartes apparaissent dans Scenario Lab, à côté des scénarios existants. Il crée de nouveaux cas nommés et personnalisés à partir d'un événement, des positions du portefeuille sélectionné et, lorsqu'un flux est configuré, de news fournies. Chaque cas est une nouvelle combinaison de paramètres d'un des sept mécanismes économiques existants ; le modèle ne crée pas une nouvelle formule de risque.

## Parcours

1. Ouvrir le **chatbot global** depuis Portfolio, Dependency Graph, Scenario Lab ou Risk Engine.
2. Décrire un événement et choisir 1 à 3 cas dans le chat. La génération s'effectue uniquement dans le chatbot.
3. Le chat confirme l'ajout et propose **View scenarios in Scenario Lab**. Les cartes nommées apparaissent à côté des scénarios existants dans la grille de Scenario Lab et restent disponibles pendant la session du navigateur.
4. Cliquer **Details** sur une carte : une modale présente le mécanisme, l'horizon, les positions, la chaîne causale, les hypothèses, les limites et les sources. Ses sections de paramètres et de requête exacte sont dépliables. Échap ferme la modale et rend le focus au bouton Details.
5. Cliquer **Run this stress case** sur la carte ou dans la modale. Le front soumet la requête exacte à `/simulate` et `/analyze` et affiche le résultat nommé dans Scenario Lab. Le bouton **Open Risk Engine** permet ensuite d'examiner la propagation et les calculs détaillés. Les décisions existantes continuent de recevoir le résultat correspondant ; leur page n'est pas modifiée.

La génération seule ne produit ni perte, ni HF/LTV calculé, ni résultat de simulation. Le dashboard et le graphe de dépendances initial restent ceux du portefeuille de départ. Les cas générés nécessitent **Engine API** : une surface enregistrée ne peut pas représenter arbitrairement leurs paramètres supplémentaires.

## Macroéconomie : hypothèses, pas équivalences

« Les États-Unis baissent les taux de 50 points de base » peut motiver des hypothèses de baisse de rendement, de variation de taux d'emprunt ou de profondeur de marché. La Fed ne fixe pas mécaniquement le funding des perpétuels ni les taux de prêt DeFi. Le bot doit expliquer le canal proposé et le caractère conditionnel des valeurs. Ces valeurs sont des hypothèses à examiner, pas des observations calibrées ou des prévisions.

« Le dollar se déprécie face à l'euro » est différent d'un dépeg d'USDe contre USD. Le moteur valorise actuellement en USD et ne modélise pas directement les engagements EUR ni le pouvoir d'achat en euros. Le bot doit annoncer cette limite et peut proposer des canaux indirects conditionnels. Il ne doit pas inventer `eur_usd` dans la requête ni présenter une perte USD comme une perte de change EUR.

Sans news fournies, l'événement saisi est **hypothétique**. Le modèle n'a pas de navigation web autonome et ne doit pas annoncer qu'une décision récente a réellement eu lieu à partir de sa mémoire.

## Configuration Gemini

Dans le `.env` à la racine, ou dans les variables du processus backend :

```dotenv
GEMINI_API_KEY=...
RISK_ASSISTANT_MODEL=gemini-3.5-flash-lite
```

La clé reste dans le backend et n'est pas incluse dans le bundle, les réponses API ou les requêtes du navigateur. `.env` est exclu de Git ; [.env.example](../.env.example) contient uniquement les noms de variables. Le modèle est configurable. Flash-Lite est le défaut de cette intégration pour le coût et la latence ; son accès a été vérifié avec la clé configurée.

Le contexte envoyé à Gemini contient l'événement et les entrées économiques utiles du portefeuille et du snapshot choisi : actifs, quantités/valeurs, dette, taux, paramètres de liquidation, distribution des emprunteurs et dépendances par identifiant. Les wallets, adresses de contrat, preuves brutes et URLs de recordings ne sont pas nécessaires et sont exclus. Le portefeuille `stress_portfolio_01` actuel contient des quantités fictives sur des marchés publics documentés, voir [ses sources](stress_portfolio.md).

Un échec d'authentification, de quota, de réseau ou de validation apparaît dans le chat. **Aucun repli silencieux vers le parseur local** dans Risk. La page Execution conserve son chatbot précédent.

## Point de branchement pour la future API de news

Aucun fournisseur de news n'a encore été choisi. Par défaut, `GET /api/v1/risk/news` retourne `status: not_configured`, avec une liste vide. Les exemples de taux et FX ne sont pas présentés comme des news récupérées.

Configurer un endpoint **HTTPS** qui fournit ce format normalisé :

```dotenv
RISK_NEWS_URL=https://votre-service/market-news
RISK_NEWS_TOKEN=... # facultatif, envoyé en Authorization: Bearer
```

```json
{
  "articles": [
    {
      "id": "provider_article_id",
      "title": "Titre de l'article fourni",
      "summary": "Résumé provenant du fournisseur",
      "url": "https://publisher.example/article",
      "published_at": "2026-10-10T15:00:00Z",
      "source": "Nom de la publication"
    }
  ]
}
```

L'URL d'exemple décrit le contrat ; aucun article fictif n'est injecté dans l'application. Si l'API choisie a un autre format, un adaptateur devra mapper ses champs à ce contrat. Le flux est lu côté serveur, au maximum 20 articles, avec des liens HTTP(S), des identifiants uniques et des dates ISO avec fuseau. Une indisponibilité ou un format invalide est signalé, sans headline inventé.

Dès que le flux fournit des articles, le chatbot affiche leurs titres, publications et dates, ainsi qu'un bouton **Use supplied news** pour préparer la demande. La génération relit le flux ; les sources des cartes correspondent aux articles réellement transmis à cet appel. Un article fourni n'est pas présenté comme vérifié indépendamment. Un article ancien conserve sa date : le moteur n'en fait pas automatiquement une information récente.

Pour une intégration serveur directe, `POST /api/v1/risk/assistant?set=stress_portfolio_01` accepte aussi `{message, count, news: {articles: [...]}}`. Le client ne fournit pas le portefeuille : le backend utilise ses propres données autoritaires.

## Validation et architecture

- `/risk/assistant-status` : présence de configuration, modèle, état de configuration des news ; aucune clé retournée.
- `/risk/news` : adaptateur de flux normalisé.
- `/risk/assistant` : contexte autoritaire → Gemini JSON → validation → propositions, sans simulation automatique.
- `/simulate` et `/analyze` : calcul financier existant après clic explicite.

Le format JSON de transport utilise le sous-ensemble portable de schéma accepté par Gemini. Le serveur conserve la validation complète : nombre de cas, longueurs, horizon, paramètres autorisés, bornes numériques, contrat de requête, existence des positions/nœuds/marchés et références à des articles réellement fournis. Tous les cas sont validés avant de retourner le lot. La probabilité du scénario reste null.

Implémentation : [risk_assistant.py](../backend/api/risk_assistant.py), [risk_news.py](../backend/api/risk_news.py), [RiskScenarioAgent.tsx](../frontend/src/RiskScenarioAgent.tsx), [api.ts](../frontend/src/data/api.ts).

Référence du format Gemini : [Structured outputs — documentation Google](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

```bash
.venv/bin/python -m pytest backend/api/tests/test_risk_assistant.py -q
cd frontend
npm run build
npm run check:assistant
```
