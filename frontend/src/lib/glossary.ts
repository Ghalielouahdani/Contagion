/**
 * Plain-language definitions shown when hovering a metric or term (see Term.tsx).
 * Keys are normalised labels (lowercase, no numbers or symbols). Keep each entry true to what
 * the engine computes (backend/risk, backend/execution) and short enough to read in a tooltip.
 */
export const glossary: Record<string, string> = {
  // portfolio
  "gross exposure": "Total value of everything held, collateral included, before subtracting debt. Not capital: borrowed money inflates it.",
  "gross": "Value of the asset held or posted as collateral, before subtracting debt.",
  "gross value": "Value of the asset held or posted as collateral, before subtracting debt.",
  "debt": "What the position owes to a lending market (borrowed stablecoins), valued at today's price.",
  "net equity": "Gross value minus debt: the capital actually at stake in the position.",
  "net equity before": "Capital at stake before the scenario: gross value minus debt, summed over positions.",
  "net equity after": "Capital left if the scenario happens: net equity before minus the conditional loss.",
  "portfolio equity before": "Capital at stake before the scenario, all positions together.",
  "portfolio equity after": "Capital left if the scenario happens, all positions together.",
  "equity after": "Capital left in the position if the scenario happens.",
  "before": "Value before the scenario, at today's prices.",
  "after": "Value if the scenario happens.",
  "positions": "Holdings in the portfolio. The same holdings are used for every stress test.",
  "carry": "Yield earned minus borrowing cost per year at today's rates. Exiting a position gives it up.",

  // losses
  "conditional loss": "What the portfolio loses if this scenario happens. Conditional: it says nothing about how likely the scenario is.",
  "conditional loss gain": "Loss if the scenario happens; a negative value is a gain (e.g. interest earned in a carry scenario).",
  "scenario loss gain": "Loss if the scenario happens; a negative value is a gain.",
  "portfolio conditional loss": "Loss of all positions together if the scenario happens, including the extra cost of sharing exit venues.",
  "loss": "Loss of the position if the scenario happens.",
  "share of loss": "Part of the portfolio loss that comes from this position.",
  "market repricing": "Loss from market prices moving (USDe, sUSDe, PT), measured at the new prices.",
  "backing impairment": "Loss from USDe losing part of its backing, or sUSDe stakers absorbing a loss through the exchange rate.",
  "liquidation penalty": "Bonus paid to liquidators when a lending position is liquidated: debt repaid times the protocol's incentive.",
  "execution haircut": "Value lost when selling into thin liquidity: the price gets worse as the order grows.",
  "bad debt": "Debt borrowers will never repay because their collateral is worth less than what they owe. Lenders absorb it.",
  "bad debt all lenders": "Debt left unrepaid after liquidations, across the whole lending market. Each lender bears its share of supply.",
  "undercollateralized debt": "Borrowers already underwater at market prices but not yet liquidatable because the oracle does not see the drop. A hidden loss for lenders.",
  "negative carry": "Yield minus borrowing cost over the horizon. A negative value is a gain.",
  "shared liquidity penalty": "Extra cost because several positions sell into the same venue at once: the joint sale moves the price more than separate sales.",
  "additional cost of shared exit venues": "Extra cost because several positions sell into the same venue at once.",
  "executable value": "What a full exit would actually realise in the scenario's liquidity, after price impact.",

  // liquidation metrics
  "health factor": "Aave: collateral value x liquidation threshold / debt. Below 1, the position can be liquidated.",
  "ltv": "Loan-to-value: debt / collateral value at the oracle price. Above the LLTV, the position can be liquidated.",
  "lltv": "Morpho's liquidation loan-to-value: the LTV above which a position can be liquidated.",
  "liquidation threshold": "Aave: share of collateral value that counts toward the health factor. Lower means liquidated sooner.",
  "liquidation threshold shift": "Change of the liquidation threshold decided by governance before the shock (negative = stricter).",
  "lt shift": "Change of the liquidation threshold decided by governance before the shock.",
  "distance to liquidation": "How far the collateral's oracle price can fall before the position becomes liquidatable.",
  "distance to liquidation now": "How far the collateral's oracle price can fall from today before the position becomes liquidatable.",
  "liquidation price": "Oracle price of the collateral at which the position becomes liquidatable.",
  "liquidation metric": "Health factor (Aave) or LTV versus LLTV (Morpho), before and after the scenario.",
  "liquidatable": "The protocol threshold is breached: liquidators may repay debt and seize collateral. Not always a full liquidation.",
  "breaks under": "Smallest shock of each kind that makes the position liquidatable. Immune: no shock size does.",
  "liquidated at": "Smallest shock of this kind that makes the position liquidatable.",
  "oracle": "Price source a lending market uses to value collateral. It can differ from the market price.",
  "oracle pass-through": "Share of a USDe market move the oracle reflects: 1 follows the market, 0 ignores it (e.g. exchange-rate or USDT-based oracles).",

  // assets and markets
  "usde": "Ethena's synthetic dollar, backed by crypto collateral and short perpetual positions.",
  "susde": "Staked USDe: earns Ethena's yield through a rising exchange rate against USDe.",
  "pt": "Pendle principal token: redeems for the underlying at maturity, so it trades at a discount before.",
  "market": "The lending market or AMM the position sits in, with its parameters.",
  "lending market": "Isolated market where lenders supply a stablecoin and borrowers post collateral.",
  "exit route": "Where the position would be sold or withdrawn, and how the exit cost is measured.",

  // scenario controls
  "usde shock": "Move of the USDe market price applied by the scenario.",
  "usde shock magnitude": "Size of the USDe market price drop. The risk engine recomputes every position.",
  "liquidity loss": "Share of exit depth that disappears in the crisis.",
  "liquidity depth reduction": "Share of exit depth that disappears: selling the same size costs more.",
  "horizon": "Number of days the scenario covers: used for yield, borrowing costs and rate scenarios.",
  "decision horizon": "Number of days the scenario covers: used for yield, borrowing costs and rate scenarios.",
  "borrow apy": "Borrowing rate applied to all debt in the carry scenario.",
  "borrow apy on all debt": "Borrowing rate applied to all debt in the carry scenario, e.g. a spike at the utilisation kink.",
  "susde apy": "sUSDe staking yield over the horizon. Negative: the exchange rate falls (reserve fund spent).",
  "susde staking apy": "sUSDe staking yield over the horizon. Negative: the exchange rate falls (reserve fund spent).",
  "failing node": "Dependency-graph node that fails: custodian, protocol, stablecoin or market.",
  "node shock": "Failure of one dependency-graph node and the share of value lost there.",
  "value lost at the node": "Share of value lost at the failing node.",

  // decision
  "exit cost": "Fees + gas + price impact of selling that share of the position before the scenario.",
  "estimated exit cost": "Fees + gas + price impact of selling that share of the position before the scenario.",
  "price impact": "Loss from the price moving against the order while selling.",
  "fees": "Trading fees paid on the exit.",
  "gas": "Ethereum transaction cost of the exit.",
  "foregone yield": "Yield given up over the horizon by exiting.",
  "residual stress loss": "Loss still suffered on the part of the position that is kept.",
  "break-even probability": "If you believe the scenario is more likely than this, exiting costs less than staying.",
  "act if probability": "Probability of the scenario above which the targeted de-risking plan pays for itself.",
  "recommendation": "STAY, REDUCE or EXIT from cost versus expected loss. INSUFFICIENT_DATA: no probability given, so no trade is forced.",
  "objective": "Exit cost + probability x residual loss + foregone yield. The lowest wins.",

  // analytics
  "usde effective leverage": "Dollars exposed to a USDe price move per dollar of net equity: 1.6x means a 10% depeg costs about 16% of equity.",
  "usde exposure": "How the portfolio reacts to USDe: threshold means no loss on small moves, then a large one past a breaking point (typical for lenders).",
  "nav at": "USDe depeg at which the portfolio loses this share of its net equity.",
  "net equity drawdown": "Share of net equity lost.",
  "top risk driver": "The assumption that moves the loss the most when varied within its range.",
  "expected loss": "Loss weighted by the probabilities you entered. Assumption-driven: the engine does not estimate probabilities.",
  "var": "Value at risk: loss not exceeded with this probability, under the probabilities you entered.",
  "expected shortfall": "Average loss in the worst cases beyond the VaR, under the probabilities you entered.",
  "inputs resting on observed data": "Share of the calculation's inputs read on-chain or from market data rather than assumed.",
  "propagation factor": "How many times the initial shock is multiplied once forced selling has played out.",

  // cascade
  "amplification": "Final price move / initial move on the most-hit asset: how much forced selling amplifies the shock.",
  "liquidation cascade": "Liquidations sell collateral, the price falls further, more borrowers become liquidatable, round after round.",
  "debt liquidated": "Borrower debt repaid by liquidators during the cascade.",
  "collateral sold": "Collateral liquidators sold on the exit venue during the round.",
  "stuck unprofitable to liquidate": "Debt that is liquidatable but no liquidator will touch: selling the collateral would cost more than the incentive.",
  "cascade round": "One step: liquidations at current prices, then the price impact of their selling.",
  "round": "One step of the cascade: liquidations at current prices, then the price impact of their selling.",
  "extra exit cost from liquidation selling": "Extra cost of the fund's exit because liquidators sell into the same venues first.",

  // risk engine page
  "break-even": "Scenario probability above which acting costs less than staying exposed.",
  "carry annual today's rates": "Yield earned minus borrowing cost per year at today's rates. Exiting gives it up.",
  "cost": "What acting costs: fees, gas, price impact and yield given up.",
  "engine loss": "Loss computed by the risk engine at this stress level.",
  "evidence": "How the dependencies behind this loss are known: verified on-chain, documented, inferred or assumed.",
  "exit": "Share of the position sold or withdrawn before the scenario.",
  "exit venue": "Where the position would be sold: a DEX route, an AMM, or a lending market's idle liquidity.",
  "liquidatable fund borrows": "Lending positions of the fund that cross their liquidation threshold in this scenario.",
  "liquidation price oracle": "Oracle price of the collateral at which the position becomes liquidatable.",
  "main mechanism": "The loss component that weighs the most for this position (repricing, impairment, liquidation, exit cost, bad debt...).",
  "portfolio loss gain": "Loss of the whole portfolio in this scenario; a negative value is a gain.",
  "price source": "Where the price comes from: an on-chain oracle, a market feed, or an assumption.",
  "price used": "Price the engine used to value this leg.",
  "probability over the horizon": "Your estimate of how likely this stress level is over the horizon. The engine never estimates it for you.",
  "provenance": "Where an input comes from: observed on-chain, derived from observed data, or assumed.",
  "quote": "Executable price obtained for selling this size, when available; otherwise a labelled proxy.",
  "reached at a usde depeg of": "Smallest USDe depeg that causes this drawdown of net equity.",
  "residual loss": "Loss still suffered on the part of the position that is kept.",
  "residual loss gain": "Loss still suffered on the part that is kept; negative values are gains.",
  "shock type": "Which mechanism is shocked: USDe market depeg, USDe backing loss or sUSDe exchange-rate cut.",
  "stress magnitude": "Severity of the scenario's main shock.",
  "this scenario": "Loss of the scenario you ran, to compare with the reference runs below.",
  "assumption range": "A model assumption that is not verified, and the range it is varied over.",
  "link with the loss": "How strongly the loss moves when this assumption moves within its range.",
  "used by": "Which calculations rely on this input.",
  "leg": "One side of the position: the asset held, the collateral, or the debt.",

  // crisis verdict (scenario assumed to happen)
  "total loss": "What the plan loses if the scenario happens: exit costs + yield given up + loss still suffered on what is kept. Lower is better.",
  "saving vs keeping everything": "How much less this plan loses than keeping every position untouched.",
  "shared venue penalty": "Extra cost because several positions sell into the same exit venue at once.",
  "loss if kept": "What the position loses if the scenario happens and nothing is done.",
  "already incurred if late": "Price loss already suffered when reacting after the move; only liquidation penalties can still be avoided.",

  // graph and evidence
  "contagion paths": "Chains of dependencies through which the shock reaches the position, each with its evidence.",
  "contagion hubs": "Nodes several positions depend on at once: one failure there hits all of them.",
  "risk channel": "How a shock travels along this link (oracle repricing, exit liquidity, exchange rate...).",
  "confidence": "How the link is known: verified on-chain, documented by the protocol, inferred by a rule, or assumed.",
  "method": "How the evidence was obtained: on-chain call, protocol API, documentation or fixture.",
  "reference": "Contract address, call or URL proving the link.",
  "observed": "When the evidence was read.",
  "verified": "Read on-chain at a pinned block, or two independent sources agree.",
  "documented": "Published by the protocol but not observable on-chain (e.g. Ethena's off-chain backing).",
  "inferred": "Derived by a stated rule, e.g. a price feed linked to an asset by its description.",
  "assumed": "Team assumption, not observed. Treat numbers that rest on it with caution.",
  "fictional": "Holdings invented for the demo; markets and prices around them can still be real.",
  "derived": "Computed from observed inputs.",
  "asset": "A token: USDe, sUSDe, a stablecoin or a PT.",
  "protocol": "A DeFi protocol: Ethena, Aave, Morpho, Pendle.",
  "position": "A holding of the portfolio.",
  "venue": "Where an asset is sold or withdrawn: a DEX route, an AMM or a lending market's idle liquidity.",
  "offchain entity": "Something outside the blockchain the position depends on, e.g. Ethena's custodians and hedges.",
  "chain": "The blockchain the position settles on.",
  "contract": "A smart contract the position depends on.",
};

/** Lowercase, drop numbers, percent signs and punctuation: "VaR 95%" -> "var", "NAV −10% at" -> "nav at". */
export function normaliseTerm(label: string): string {
  return label
    .toLowerCase()
    .replace(/[0-9]+([.,][0-9]+)?/g, " ")
    .replace(/[%×·()/:>≤≥<→+\-−_]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const index: Record<string, string> = Object.fromEntries(Object.entries(glossary).map(([key, text]) => [normaliseTerm(key), text]));

export function explain(label: string): string | undefined {
  return index[normaliseTerm(label)];
}
