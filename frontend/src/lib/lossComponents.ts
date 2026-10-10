/** Display names of the risk engine's loss components (risk_result.positions[].loss_components). */
export const COMPONENT_COPY: Record<string, string> = {
  market_repricing: "Market repricing",
  backing_impairment: "Backing loss / rate cut",
  liquidation_penalty: "Liquidation penalty",
  execution_haircut: "Execution cost of exiting",
  negative_carry: "Carry over the horizon",
  bad_debt: "Bad debt (realised)",
  undercollateralized_debt: "Underwater debt (not yet realised)",
  protocol_failure: "Protocol failure",
  limited_liability: "Loss above equity (left to lenders)",
  shared_liquidity_penalty: "Shared exit venues (portfolio only)",
};

/** Short names for chart axes. */
export const COMPONENT_SHORT: Record<string, string> = {
  market_repricing: "Repricing",
  backing_impairment: "Backing",
  liquidation_penalty: "Liquidation",
  execution_haircut: "Exit cost",
  negative_carry: "Carry",
  bad_debt: "Bad debt",
  undercollateralized_debt: "Underwater",
  protocol_failure: "Protocol",
  limited_liability: "Equity cap",
  shared_liquidity_penalty: "Shared exit",
};
