import type { AssistantResponse, ScenarioInputs, ScenarioKind } from "../lib/types";

/** Local, constrained text-to-scenario translator. It never predicts losses or runs the engine. */
export function proposeScenario(
  message: string,
  defaults: (kind: ScenarioKind) => ScenarioInputs,
  available: ScenarioKind[],
  nodes: string[],
): AssistantResponse | null {
  const text = message.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const generating = /\b(cree|creer|genere|generer|propose|prepare|teste|tester|simule|simuler|create|generate|draft|test|simulate|run)\b/.test(text);
  const percent = /%|pour\s*cent|percent|points?/.test(text);
  if (!generating && !percent) return null;
  const fail = (reason: string): AssistantResponse => ({ message: `${reason} No scenario was applied or run. Try: “USDe falls 10%, liquidity falls 80%, over 7 days”.`, actions: [] });
  const hasLiquidity = /liquidite|liquidity|profondeur|depth/.test(text);
  const hasDepeg = /depeg|decote|depreciation|\busde\b/.test(text);
  let scenario: ScenarioKind | null = null;
  if (/cascade|contagion|spiral|domino/.test(text)) scenario = "liquidation_cascade";
  else if (/gouvernance|governance|seuil|threshold|oracle/.test(text)) scenario = "governance_change";
  else if (/carry|funding|rendement|apy|emprunt|borrow|taux/.test(text)) scenario = "carry_squeeze";
  else if (/noeud|node|backing|custodian|depositaire|exploit|hack|failure|defaillance|panne/.test(text)) scenario = "node_shock";
  else if (/combine|combined/.test(text) || hasDepeg && hasLiquidity) scenario = "combined_crisis";
  else if (hasLiquidity) scenario = "liquidity_crisis";
  else if (hasDepeg) scenario = "usde_depeg";
  else {
    const letter = text.match(/scenario\s*([a-g])\b/)?.[1];
    scenario = letter ? ({ a: "usde_depeg", b: "liquidity_crisis", c: "combined_crisis", d: "carry_squeeze", e: "governance_change", f: "node_shock", g: "liquidation_cascade" } as const)[letter as "a"] : null;
  }
  if (!scenario && /\b(exit|reduce|compare)\b/.test(text)) return null;
  if (!scenario) return fail("Describe one of the seven supported stresses: USDe depeg, liquidity, combined, carry, governance, node failure or liquidation cascade.");
  if (!available.includes(scenario)) return fail("This portfolio has no data for the requested scenario.");
  // Do not silently discard another asset's price shock, or invert a positive price move.
  if (/\b(eth|btc|weth|bitcoin|ethereum)\b/.test(text)) return fail("This engine does not model ETH/BTC price shocks. Its current pricing rules cover USDe, sUSDe, PT and supported stablecoins.");
  if (hasDepeg && /(?:\busde\b[^,;%\n]{0,30}(?:hausse|augmente|monte|rise|rises|rising|increase|increases)|(?:hausse|increase|rise)[^,;%\n]{0,20}\busde\b)/.test(text) && scenario !== "carry_squeeze") return fail("The USDe control currently supports depreciation, not a price increase.");

  if (hasLiquidity && /(?:liquidite|liquidity|profondeur|depth)[^,;%\n]{0,30}(?:hausse|augmente|monte|rise|rises|increase|increases)/.test(text)) return fail("The liquidity control describes depth removed, not an increase in liquidity.");

  const inputs = { ...defaults(scenario) };
  const entered = new Set<keyof ScenarioInputs>();
  const captured: Array<{ start: number; end: number }> = [];
  const n = "([+-]?\\d+(?:[.,]\\d+)?)";
  const unit = "(?:%|pour\\s*cent|percent|points?|pts?)";
  const grab = (anchor: string): number | undefined => {
    // Anchors keep each percentage attached to its economic input; never reuse the first number.
    const regex = new RegExp(`(?:${anchor})[^%\\d;,\\n+.-]{0,45}${n}\\s*${unit}`, "g");
    const matches = [...text.matchAll(regex)];
    if (!matches.length) return undefined;
    if (matches.length > 1) throw new Error("Several values were supplied for the same parameter. Keep one value per input.");
    const m = matches[0];
    if (captured.some(c => m.index! < c.end && m.index! + m[0].length > c.start))
      throw new Error("One percentage appears attached to two inputs. Separate USDe and liquidity values with a comma.");
    captured.push({ start: m.index!, end: m.index! + m[0].length });
    return Number(m[1].replace(",", "."));
  };
  const set = (key: keyof ScenarioInputs, value: number | undefined, min: number, max: number, magnitude = false) => {
    if (value === undefined) return;
    const v = magnitude ? Math.abs(value) : value;
    if (!Number.isFinite(v) || v < min || v > max) throw new Error(`${key} must be between ${min} and ${max}.`);
    Object.assign(inputs, { [key]: v });
    entered.add(key);
  };
  try {
    const days = [...text.matchAll(/([+-]?\d+(?:[.,]\d+)?)\s*(?:jours?|days?|j)\b/g)];
    if (days.length > 1) throw new Error("Use one horizon in days.");
    if (/\b(semaines?|weeks?|mois|months?|ans|years?)\b/.test(text)) throw new Error("Specify the horizon in days (1–30).");
    const horizon = days.length ? Number(days[0][1].replace(",", ".")) : undefined;
    if (horizon !== undefined && !Number.isInteger(horizon)) throw new Error("Use a whole number of days (1–30).");
    set("horizonDays", horizon, 1, 30);
    if (["usde_depeg", "combined_crisis", "governance_change", "liquidation_cascade"].includes(scenario))
      set("shockPct", grab("\\busde\\b|depeg|decote|depreciation|choc(?:\\s+initial)?|shock"), 1, 40, true);
    if (["liquidity_crisis", "combined_crisis", "liquidation_cascade"].includes(scenario))
      set("liquidityLossPct", grab("liquidite|liquidity|profondeur|depth"), 0, 95, true);
    if (scenario === "carry_squeeze") {
      set("borrowApyPct", grab("emprunt|borrow(?:\\s+(?:rate|apy))?|taux\\s+(?:de\\s+)?d[' ]?emprunt"), 0, 100);
      set("susdeApyPct", grab("susde|rendement(?:\\s+susde)?|staking"), -10, 15);
    }
    if (scenario === "governance_change") {
      const shift = grab("seuils?|thresholds?|lltv|lt shift");
      const down = /(?:baisse|lower|reduce|reduit|dimin)[^;,.]{0,25}(?:seuil|threshold)|(?:seuil|threshold)[^;,.\d]{0,30}(?:baisse|lower|reduce|reduit|dimin)/.test(text);
      set("ltShiftPct", shift === undefined ? undefined : down ? -Math.abs(shift) : shift, -15, 5);
    }
    if (scenario === "node_shock") {
      const explicit = message.match(/(?:asset|protocol|market|offchain):[\w.-]+/)?.[0];
      if (explicit) {
        if (!nodes.includes(explicit)) throw new Error("This node is absent from the portfolio dependency graph.");
        inputs.nodeId = explicit;
        entered.add("nodeId");
      } else if (/backing|ethena/.test(text)) {
        inputs.nodeId = "offchain:ethena_backing";
        entered.add("nodeId");
      } else if (nodes.some(node => node.startsWith("protocol:") && new RegExp(`\\b${node.split(":")[1]}\\b`).test(text))) {
        inputs.nodeId = nodes.find(node => node.startsWith("protocol:") && new RegExp(`\\b${node.split(":")[1]}\\b`).test(text))!;
        entered.add("nodeId");
      } else throw new Error("Specify the graph node to shock, for example offchain:ethena_backing or protocol:aave.");
      if (!nodes.includes(inputs.nodeId)) throw new Error("This node is absent from the portfolio dependency graph.");
      set("nodeLossPct", grab("perte|loss|backing|haircut|choc|shock|failure|defaillance"), 0, 50, true);
    }
    // Every written percentage must be accounted for. Unsupported beta/oracle/absorption
    // inputs are refused rather than quietly simulated at a different value.
    for (const m of text.matchAll(new RegExp(`${n}\\s*${unit}`, "g"))) {
      if (!captured.some(c => m.index! >= c.start && m.index! + m[0].length <= c.end))
        throw new Error(`I cannot attach “${m[0]}” to a supported input. Put each value after USDe, liquidity, borrow, sUSDe, threshold or loss.`);
    }
  } catch (error) { return fail(error instanceof Error ? error.message : "Ambiguous parameters."); }

  const keys: Array<keyof ScenarioInputs> = ["horizonDays"];
  if (["usde_depeg", "combined_crisis", "governance_change", "liquidation_cascade"].includes(scenario)) keys.push("shockPct");
  if (["liquidity_crisis", "combined_crisis", "liquidation_cascade"].includes(scenario)) keys.push("liquidityLossPct");
  if (scenario === "carry_squeeze") keys.push("susdeApyPct", "borrowApyPct");
  if (scenario === "governance_change") keys.push("ltShiftPct");
  if (scenario === "node_shock") keys.push("nodeId", "nodeLossPct");
  const labels: Record<keyof ScenarioInputs, string> = { horizonDays: "Horizon (days)", shockPct: "USDe depreciation (%)", liquidityLossPct: "Liquidity depth removed (%)", ltShiftPct: "Threshold shift (points)", susdeApyPct: "sUSDe annual rate (%)", borrowApyPct: "Borrow annual rate (%)", nodeId: "Target node", nodeLossPct: "Node value lost (%)" };
  return {
    message: "Scenario prepared from your text. Review the parameters below, then apply it to Scenario Lab. No simulation has run yet; losses will come from the risk engine.",
    actions: [],
    proposal: { scenario, inputs, sourceText: message, parameters: keys.map(key => ({ label: labels[key], value: String(inputs[key]), source: entered.has(key) ? "Your text" : "Portfolio preset" })) },
  };
}
