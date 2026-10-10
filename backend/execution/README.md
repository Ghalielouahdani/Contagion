# backend/execution/ — owner: P3 (Decision, Liquidity & Exit Optimization)

The decision engine. It answers: **"should I stay, reduce or exit this position, and is the exit worth what it costs?"**

```
portfolio + market_snapshot + risk_result + scenario_request  ──►  decision_result.json
```

Read: blueprint sections 8 (objective, break-even, recommendation rules), 7.2 (exit-cost proxy), 4.2 (conventions), 11.8 (golden output), 16 P3.

## What to do, step by step

1. **Five options per position:** exit 0%, 25%, 50%, 75% or 100%. Decisions are per position in v1. Exits happen **before** the shock, at pre-shock prices and with normal (pre-crisis) depth.
2. **Exit cost of each option** = fees + gas + price impact.
   - Token / PT: sell x × quantity on the position's exit venue.
   - Borrow position: pro-rata unwind. Withdraw x × collateral, sell it, repay x × debt.
   - Price impact: use the best available quote, in priority order executable → pool reserves → proxy (size² / (depth + size)). Set `quote_status` accordingly.
3. **Residual loss** = (1 − x) × the position's `conditional_loss_usd` from risk_result.
4. **Foregone yield** = x × carry over the horizon. Carry = collateral or token APY × value − borrow APY × debt, using `market_snapshot.yields`. Cash earns 0.
5. **Break-even probability** of each option vs staying:
   p*(x) = (ExitCost(x) + ForegoneYield(x)) / (ResidualLoss(0) − ResidualLoss(x))
   In plain terms: "if you think this scenario has more than p* chance of happening, this option is worth it."
6. **Recommendation** (section 8 rules):
   - no probability given → `INSUFFICIENT_DATA` plus the full table and every p*, never a fake "optimal" trade;
   - probability given and real quotes available → minimize J(x) = cost + p × residual + foregone yield; x = 0 → STAY, 0 < x < 1 → REDUCE, x = 1 → EXIT;
   - only proxy quotes available → show the result but flag it.

## Golden values (aave_01, depeg)

Full exit costs 32,742.97 and has a break-even probability of 22.48%. A 25% exit costs 2,660.32 and has a break-even probability of 7.75%. Reproduce all five rows of section 11.8.

## Required tests

0% exit costs 0. A bigger exit costs more (convex). No incident → STAY. The recommendation moves sensibly when the probability or the slippage changes. A case where a partial exit wins. The golden values.

## Pitfalls

- Never compare a certain cost with an unweighted scenario loss as if the scenario were certain.
- Use the same horizon for costs, losses and yield.
