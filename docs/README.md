# docs/ — project documentation (shared; demo material owned by P4)

## What goes here

1. **Blueprint:** the reference spec (`DeFi_Contagion_Project_Blueprint_v2.md`, currently at the repo root). Any change to scope or contracts is recorded there.
2. **Verified-market log (P1):** [verified_markets.md](verified_markets.md) (done for 10 Oct 2026). for each real market used, write down the protocol, market ID or address, oracle address and type, key parameters, block number, date checked and source link. This is the proof behind every `verified: true`.
3. **Assumptions register (P2/P3):** every `assumed` value (yields, venue depth, PT yield shock, fees, gas…), why it was chosen, and how sensitive results are to it.
4. **Demo script (P4):** the exact click path for the 3-minute demo, the talking points for each screen, and what to do if the network fails.
5. **Risk engine plan (P2):** [risk_engine_plan.md](risk_engine_plan.md) — roadmap, differentiators and progress checklist; [risk_backtest.md](risk_backtest.md) — the engine against real history.
6. **Pitch material (P4 + everyone):** slides, screenshots, backup recording.

## Rule

If someone asks "where does this number come from?", the answer must be findable in this folder or in an edge's evidence.

## Comprendre et valider le Risk Engine

- [Guide des calculs et des sorties affichées](risk_engine_explained.md) : unités, formules, chaque scénario, liquidation, prêteurs, cascade, incertitude et graphiques.
- [Backtest historique et APIs](historical_backtest.md) : données réellement collectées, protocole sans look-ahead et limites de validation.
- [Résultats historiques reproductibles](backtests/results.md) : tableaux calculés par le moteur, avec les entrées et sorties JSON archivées.
