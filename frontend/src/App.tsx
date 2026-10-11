import { AnimatePresence, motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ReactFlow, {
  Background,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
  Node,
  Panel,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import {
  AlertTriangle,
  ArrowUpDown,
  BadgeCheck,
  BarChart3,
  ChevronDown,
  Command,
  Database,
  Eye,
  EyeOff,
  Fingerprint,
  Mic,
  MicOff,
  GitBranch,
  LogOut,
  Moon,
  Play,
  RefreshCw,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Volume2,
  VolumeX,
  WalletCards,
  X,
} from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { createActionRegistry } from "./actions/registry";
import { defaultDataMode, loadAppData, postAssistantMessage, presetInputs } from "./data/api";
import { compactId, labelize, money, percent, signedPercent } from "./lib/format";
import type {
  AppData,
  AssistantMessage,
  DashboardAction,
  DataMode,
  DependencyGraph,
  GraphEdge,
  GraphNode,
  Portfolio,
  PortfolioPosition,
  RiskPosition,
  ScenarioInputs,
  ScenarioKind,
  View,
} from "./lib/types";

type Theme = "light" | "dark";
type SortKey = "protocol" | "gross_value_usd" | "debt_value_usd" | "net_equity_usd";
type AssistantState = "idle" | "listening" | "thinking" | "speaking";
type AssistantInputMode = "text" | "voice";
type AuthSession = { email: string; signedInAt: string; method: "password" | "webauthn" };
type AuthStatus = "idle" | "checking" | "success" | "error";
type AuthMode = "signin" | "signup";
type LocalDemoAccount = { email: string; password: string; createdAt: string };

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  }
}

const viewMeta: Record<View, { label: string; icon: typeof WalletCards; section: string }> = {
  portfolio: { label: "Portfolio Dashboard", icon: WalletCards, section: "Explore" },
  graph: { label: "Dependency Graph", icon: GitBranch, section: "Explore" },
  scenario: { label: "Scenario Lab", icon: SlidersHorizontal, section: "Run" },
  decision: { label: "Decision Engine", icon: BarChart3, section: "Run" },
};

const scenarioCopy: Record<ScenarioKind, { title: string; preset: string; summary: string }> = {
  usde_depeg: {
    title: "USDe depeg",
    preset: "A · -5% spot shock",
    summary: "USDe market price falls. sUSDe and PT reprice; lending positions move toward liquidation only if their oracle follows the market.",
  },
  liquidity_crisis: {
    title: "Liquidity crisis",
    preset: "B · -80% exit depth",
    summary: "Reference marks can remain stable while executable exits degrade through thin shared venues.",
  },
  combined_crisis: {
    title: "Depeg + liquidity crisis",
    preset: "C · -30% and -80% depth",
    summary: "The depeg triggers liquidations whose forced selling hits the same thin venues before the fund can exit.",
  },
  governance_change: {
    title: "Governance or oracle change",
    preset: "E · LT -5 pts, then -27%",
    summary: "A protocol lowers liquidation thresholds or switches oracle, then the depeg hits on the new parameters.",
  },
  carry_squeeze: {
    title: "Carry squeeze",
    preset: "D · sUSDe 0%, borrow 60%",
    summary: "No price shock: funding turns, the staking yield vanishes and borrow rates spike at the utilization kink.",
  },
  node_shock: {
    title: "Dependency node failure",
    preset: "F · Ethena backing -10%",
    summary: "One node of the dependency graph fails (custodian, protocol, stablecoin) and the loss follows every path to it.",
  },
};

const scenarioOrder: ScenarioKind[] = ["usde_depeg", "liquidity_crisis", "combined_crisis", "governance_change", "carry_squeeze", "node_shock"];

// Controls shown per scenario (the horizon is always shown).
const scenarioControls: Record<ScenarioKind, Array<"shock" | "liquidity" | "ltShift" | "carry" | "node">> = {
  usde_depeg: ["shock"],
  liquidity_crisis: ["liquidity"],
  combined_crisis: ["shock", "liquidity"],
  governance_change: ["shock", "ltShift"],
  carry_squeeze: ["carry"],
  node_shock: ["node"],
};

// Starting values of the scenario-specific controls, matching the fixture presets.
const defaultExtraInputs = { ltShiftPct: -5, susdeApyPct: 0, borrowApyPct: 60, nodeId: "offchain:ethena_backing", nodeLossPct: 10 };
type ExtraInputs = typeof defaultExtraInputs;

// Left to right follows the direction of dependency: position -> market / exit venue -> oracle -> asset -> protocol.
const graphColumn: Record<string, number> = {
  position: 0,
  market: 1,
  venue: 1,
  oracle: 2,
  contract: 2,
  asset: 3,
  protocol: 4,
  offchain_entity: 4,
  chain: 4,
};
const typeOrder = ["position", "market", "venue", "oracle", "contract", "asset", "protocol", "offchain_entity", "chain"];
const easeOut = [0.22, 1, 0.36, 1] as const;
const staggerGroup = {
  hidden: {},
  show: { transition: { staggerChildren: 0.065, delayChildren: 0.04 } },
};
const riseItem = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.34, ease: easeOut } },
};

function layoutGraph(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const columns = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const column = graphColumn[node.type] ?? 4;
    columns.set(column, [...(columns.get(column) ?? []), node]);
  }
  const positions: Record<string, { x: number; y: number }> = {};
  columns.forEach((items, column) => {
    items
      .sort((a, b) => typeOrder.indexOf(a.type) - typeOrder.indexOf(b.type) || a.id.localeCompare(b.id))
      .forEach((node, row) => {
        positions[node.id] = { x: 40 + column * 270, y: 30 + row * 96 };
      });
  });
  return positions;
}

const confidenceTone: Record<string, string> = {
  verified: "good",
  documented: "info",
  inferred: "warn",
  assumed: "warn",
};

const nodeTypeColor: Record<string, string> = {
  asset: "var(--np-accent-blue)",
  protocol: "var(--np-accent-coral)",
  market: "var(--np-accent-gold)",
  oracle: "var(--np-accent-periwinkle)",
  position: "var(--np-strong)",
  venue: "var(--np-accent-lilac)",
  offchain_entity: "var(--np-accent-coral)",
};

const sections = [
  { label: "Explore", items: ["portfolio", "graph"] as View[] },
  { label: "Run", items: ["scenario", "decision"] as View[] },
];

const demoCredential = {
  email: "demo@belem.capital",
  username: "demo",
  password: "demo",
};
const sessionStorageKey = "defi-contagion-session";
const accountsStorageKey = "defi-contagion-demo-accounts";
const rememberedIdentifierKey = "defi-contagion-remembered-email";
const passkeyStorageKey = "defi-contagion-demo-passkey";
const demoUserId = "defi-contagion-demo-user";

function App() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [view, setView] = useState<View>("portfolio");
  const [scenario, setScenario] = useState<ScenarioKind>("usde_depeg");
  const [mode, setMode] = useState<DataMode>(defaultDataMode);
  const [theme, setTheme] = useState<Theme>("light");
  const [selectedPosition, setSelectedPosition] = useState("ethena_susde_01");
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [hoveredPosition, setHoveredPosition] = useState<string | null>(null);
  const [inspectedExitFraction, setInspectedExitFraction] = useState<string | null>(null);
  const [shockPct, setShockPct] = useState(5);
  const [horizonDays, setHorizonDays] = useState(7);
  const [liquidityLossPct, setLiquidityLossPct] = useState(80);
  const [extraInputs, setExtraInputs] = useState<ExtraInputs>(defaultExtraInputs);
  const setExtraInput = <K extends keyof ExtraInputs>(key: K, value: ExtraInputs[K]) =>
    setExtraInputs((current) => ({ ...current, [key]: value }));

  // Picking a scenario loads its preset values, so the screen shows the preset the card announces.
  function selectScenario(kind: ScenarioKind) {
    const preset = presetInputs(kind);
    setScenario(kind);
    if (preset.shockPct !== undefined) setShockPct(preset.shockPct);
    if (preset.liquidityLossPct !== undefined) setLiquidityLossPct(preset.liquidityLossPct);
    if (preset.horizonDays !== undefined) setHorizonDays(preset.horizonDays);
    const { ltShiftPct, susdeApyPct, borrowApyPct, nodeId, nodeLossPct } = preset;
    setExtraInputs((current) => ({
      ltShiftPct: ltShiftPct ?? current.ltShiftPct,
      susdeApyPct: susdeApyPct ?? current.susdeApyPct,
      borrowApyPct: borrowApyPct ?? current.borrowApyPct,
      nodeId: nodeId ?? current.nodeId,
      nodeLossPct: nodeLossPct ?? current.nodeLossPct,
    }));
  }
  const [commandOpen, setCommandOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hasRun, setHasRun] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [introOpen, setIntroOpen] = useState(true);

  // Deferred so dragging a slider does not queue a request per pixel; the result follows the slider.
  const deferredShock = useDeferredValue(shockPct);
  const deferredHorizon = useDeferredValue(horizonDays);
  const deferredLiquidity = useDeferredValue(liquidityLossPct);
  const deferredExtra = useDeferredValue(extraInputs);
  const scenarioInputs: ScenarioInputs = { shockPct, horizonDays, liquidityLossPct, ...extraInputs };
  const appQuery = useQuery({
    queryKey: ["app-data", mode, scenario, deferredShock, deferredHorizon, deferredLiquidity, deferredExtra],
    queryFn: () =>
      loadAppData(mode, scenario, {
        shockPct: deferredShock,
        horizonDays: deferredHorizon,
        liquidityLossPct: deferredLiquidity,
        ...deferredExtra,
      }),
    placeholderData: (previousData) => previousData,
    enabled: Boolean(session),
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    clearStoredSession();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
      if (event.key === "Escape") setCommandOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const rawData = appQuery.data;
  // Show the decision of the selected position (the engine computes one per position).
  const data = rawData ? { ...rawData, decision: rawData.decisions[selectedPosition] ?? rawData.decision } : undefined;
  const selectedRisk = data?.risk.positions.find((position) => position.position_id === selectedPosition) ?? data?.risk.positions[0];
  const selectedPortfolio =
    data?.portfolio.positions.find((position) => position.position_id === selectedPosition) ?? data?.portfolio.positions[0];

  useEffect(() => {
    if (!data?.portfolio.positions.length) return;
    if (!data.portfolio.positions.some((position) => position.position_id === selectedPosition)) {
      setSelectedPosition(data.portfolio.positions[0].position_id);
    }
  }, [data?.portfolio.positions, selectedPosition]);

  function runScenario() {
    setHasRun(true);
    setView("decision");
  }

  function executeAction(action: DashboardAction) {
    if (action.type === "navigate_view") setView(action.view);
    if (action.type === "select_position") {
      setSelectedPosition(action.positionId);
      if (action.view) setView(action.view);
    }
    if (action.type === "set_scenario") {
      selectScenario(action.scenario);
    }
    if (action.type === "set_shock") {
      setShockPct(action.shockPct);
      setView("scenario");
    }
    if (action.type === "set_horizon") {
      setHorizonDays(action.days);
      setView("scenario");
    }
    if (action.type === "set_liquidity_loss") {
      setLiquidityLossPct(action.percent);
      setView("scenario");
    }
    if (action.type === "run_simulation") {
      if (action.scenario && action.scenario !== scenario) selectScenario(action.scenario);
      setHasRun(true);
      setView("decision");
    }
    if (action.type === "open_graph_for_position") {
      setSelectedPosition(action.positionId);
      setView("graph");
    }
    if (action.type === "set_exit_fraction") {
      setInspectedExitFraction(action.fraction);
      setView("decision");
    }
    if (action.type === "toggle_data_mode") setMode((current) => (current === "fixture" ? "api" : "fixture"));
    if (action.type === "toggle_theme") setTheme((current) => (current === "light" ? "dark" : "light"));
  }

  function reset() {
    setScenario("usde_depeg");
    setMode("fixture");
    setSelectedPosition("ethena_susde_01");
    setSelectedEdge(null);
    setShockPct(5);
    setHorizonDays(7);
    setLiquidityLossPct(80);
    setExtraInputs(defaultExtraInputs);
    setInspectedExitFraction(null);
    setHasRun(true);
    setView("portfolio");
  }

  function handleAuthenticated(nextSession: AuthSession) {
    setSession(nextSession);
  }

  function signOut() {
    clearStoredSession();
    setSession(null);
    setAssistantOpen(false);
    setCommandOpen(false);
  }

  const dismissIntro = useCallback(() => {
    setIntroOpen(false);
  }, []);

  function replayIntro() {
    setIntroOpen(true);
  }

  if (!session) {
    return (
      <>
        <AnimatePresence mode="wait">
          {!introOpen ? (
            <motion.div
              key="login"
              initial={{ opacity: 0, scale: 0.992 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.992 }}
              transition={{ duration: 0.62, ease: easeOut }}
            >
              <LoginScreen theme={theme} setTheme={setTheme} onAuthenticated={handleAuthenticated} />
            </motion.div>
          ) : null}
        </AnimatePresence>
        <IntroOverlay open={introOpen} onComplete={dismissIntro} />
      </>
    );
  }

  return (
    <>
    <main className="app-shell">
      <Sidebar
        view={view}
        setView={setView}
        mode={mode}
        setMode={setMode}
        theme={theme}
        setTheme={setTheme}
        health={data?.health}
        onSignOut={signOut}
        session={session}
      />

      <section className="content-pane">
        <header className="topbar">
          <div className="topbar-brand">
            <div className="topbar-mark" aria-hidden="true">
              <DeFiLogo compact />
            </div>
            <div>
              <p className="eyebrow">DeFi Contagion Explorer</p>
              <AnimatedHeading text={viewMeta[view].label} />
              <motion.p className="lead" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.34, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}>
                {scenarioCopy[scenario].summary}
              </motion.p>
            </div>
          </div>
          <div className="topbar-actions">
            <button className="icon-button text-button" onClick={() => setCommandOpen(true)}>
              <Command size={15} />
              Cmd K
            </button>
            <button className="icon-button text-button" onClick={reset}>
              <RefreshCw size={15} />
              Reset
            </button>
            <button className="icon-button text-button" onClick={replayIntro}>
              <Sparkles size={15} />
              Replay intro
            </button>
            <button className="run-button" onClick={runScenario}>
              <Play size={15} />
              Run scenario
            </button>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.div
            key={`${view}-${scenario}-${mode}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            {appQuery.isLoading ? <SkeletonView /> : null}
            {appQuery.isError ? <ErrorView mode={mode} /> : null}
            {data ? (
              <>
                {view === "portfolio" ? (
                  <PortfolioDashboard
                    data={data}
                    selectedPosition={selectedPosition}
                    setSelectedPosition={setSelectedPosition}
                    setView={setView}
                    hoveredPosition={hoveredPosition}
                    setHoveredPosition={setHoveredPosition}
                  />
                ) : null}
                {view === "graph" ? (
                  <ReactFlowProvider>
                    <DependencyGraphView
                      graph={data.graph}
                      risk={data.risk}
                      scenario={scenario}
                      selectedPosition={selectedPosition}
                      setSelectedPosition={setSelectedPosition}
                      selectedEdge={selectedEdge}
                      setSelectedEdge={setSelectedEdge}
                      hoveredPosition={hoveredPosition}
                      setHoveredPosition={setHoveredPosition}
                    />
                  </ReactFlowProvider>
                ) : null}
                {view === "scenario" ? (
                  <ScenarioLab
                    data={data}
                    scenario={scenario}
                    setScenario={selectScenario}
                    selectedPosition={selectedPosition}
                    setSelectedPosition={setSelectedPosition}
                    hoveredPosition={hoveredPosition}
                    setHoveredPosition={setHoveredPosition}
                    shockPct={shockPct}
                    setShockPct={setShockPct}
                    horizonDays={horizonDays}
                    setHorizonDays={setHorizonDays}
                    liquidityLossPct={liquidityLossPct}
                    setLiquidityLossPct={setLiquidityLossPct}
                    extraInputs={extraInputs}
                    setExtraInput={setExtraInput}
                    runScenario={runScenario}
                  />
                ) : null}
                {view === "decision" ? (
                  <DecisionEngine
                    data={data}
                    scenario={scenario}
                    scenarioInputs={scenarioInputs}
                    hasRun={hasRun}
                    selectedRisk={selectedRisk}
                    selectedPortfolio={selectedPortfolio}
                    selectedPosition={selectedPosition}
                    setSelectedPosition={setSelectedPosition}
                    hoveredPosition={hoveredPosition}
                    setHoveredPosition={setHoveredPosition}
                    inspectedExitFraction={inspectedExitFraction}
                    setInspectedExitFraction={setInspectedExitFraction}
                    setView={setView}
                  />
                ) : null}
              </>
            ) : null}
          </motion.div>
        </AnimatePresence>
      </section>

      <CommandPalette
        open={commandOpen}
        query={query}
        setQuery={setQuery}
        setOpen={setCommandOpen}
        data={data}
        executeAction={executeAction}
      />
      {data ? (
        <AssistantDock
          open={assistantOpen}
          setOpen={setAssistantOpen}
          stateData={data}
          mode={mode}
          view={view}
          scenario={scenario}
          selectedPosition={selectedPosition}
          inspectedExitFraction={inspectedExitFraction}
          scenarioInputs={scenarioInputs}
          executeAction={executeAction}
        />
      ) : null}
    </main>
    <IntroOverlay open={introOpen} onComplete={dismissIntro} />
    </>
  );
}

function IntroOverlay({ open, onComplete }: { open: boolean; onComplete: () => void }) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const ecosystem = ["Ethena", "Aave", "Morpho", "Pendle"];
  const title = "DeFi Contagion";

  useEffect(() => {
    if (!open) return;
    const timeout = window.setTimeout(onComplete, prefersReducedMotion ? 900 : 3600);
    return () => window.clearTimeout(timeout);
  }, [onComplete, open, prefersReducedMotion]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="intro-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="DeFi Contagion intro"
          initial={{ opacity: 1 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, scale: prefersReducedMotion ? 1 : 1.018 }}
          transition={{ duration: prefersReducedMotion ? 0.18 : 0.82, ease: easeOut }}
        >
          <div className="intro-noise" aria-hidden="true" />
          <motion.div
            className="intro-logo"
            initial={{ opacity: 0, x: prefersReducedMotion ? 0 : -34, scale: 0.92 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            transition={{ duration: prefersReducedMotion ? 0.16 : 0.72, delay: prefersReducedMotion ? 0 : 0.2, ease: easeOut }}
          >
            <DeFiLogo />
          </motion.div>
          <motion.div
            className="intro-orbit"
            aria-hidden="true"
            initial={{ opacity: 0, scale: 0.82 }}
            animate={{ opacity: prefersReducedMotion ? 0.18 : 0.42, scale: 1, rotate: prefersReducedMotion ? 0 : 8 }}
            transition={{ duration: prefersReducedMotion ? 0.2 : 2.1, ease: easeOut }}
          />
          <motion.div
            className="intro-panel"
            initial={{ opacity: 0, x: prefersReducedMotion ? 0 : -58 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, y: prefersReducedMotion ? 0 : -18 }}
            transition={{ duration: prefersReducedMotion ? 0.18 : 0.9, ease: easeOut }}
          >
            <div className="intro-kicker">
              {ecosystem.map((item, index) => (
                <motion.span
                  key={item}
                  initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.36, delay: prefersReducedMotion ? 0 : 0.28 + index * 0.14, ease: easeOut }}
                >
                  {item}
                </motion.span>
              ))}
            </div>
            <h1 className="intro-wordmark" aria-label={title}>
              {title.split("").map((letter, index) => (
                <motion.span
                  key={`${letter}-${index}`}
                  aria-hidden="true"
                  initial={{ opacity: 0, x: prefersReducedMotion ? 0 : -24 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.44, delay: prefersReducedMotion ? 0 : 0.78 + index * 0.035, ease: easeOut }}
                >
                  {letter === " " ? "\u00A0" : letter}
                </motion.span>
              ))}
            </h1>
            <motion.p
              className="intro-tagline"
              initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.54, delay: prefersReducedMotion ? 0 : 1.72, ease: easeOut }}
            >
              Mapping hidden dependency risk before stress becomes contagion.
            </motion.p>
            <motion.div
              className="intro-resolve"
              aria-hidden="true"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: prefersReducedMotion ? 0.16 : 0.9, delay: prefersReducedMotion ? 0 : 2.02, ease: easeOut }}
            />
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function DeFiLogo({ compact = false }: { compact?: boolean }) {
  return (
    <svg className={compact ? "defi-logo defi-logo--compact" : "defi-logo"} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <circle cx="32" cy="32" r="4.8" fill="currentColor" />
      <path d="M32 12C43 12 52 21 52 32" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M32 52C21 52 12 43 12 32" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M20 22C24.5 16.8 31.4 15.2 38 17" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" opacity="0.46" />
      <path d="M44 42C39.5 47.2 32.6 48.8 26 47" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" opacity="0.46" />
      <circle cx="48.5" cy="27.5" r="2.7" fill="currentColor" opacity="0.72" />
      <circle cx="15.5" cy="36.5" r="2.7" fill="currentColor" opacity="0.72" />
    </svg>
  );
}

function LoginScreen({
  theme,
  setTheme,
  onAuthenticated,
}: {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  onAuthenticated: (session: AuthSession) => void;
}) {
  const [authMode, setAuthMode] = useState<AuthMode>("signin");
  const [identifier, setIdentifier] = useState(() => localStorage.getItem(rememberedIdentifierKey) ?? demoCredential.email);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [rememberEmail, setRememberEmail] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState<AuthStatus>("idle");
  const [error, setError] = useState("");
  const [webauthnSupported, setWebauthnSupported] = useState(false);
  const [biometricLabel, setBiometricLabel] = useState("Touch ID");
  const passwordRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    let active = true;
    async function checkWebAuthn() {
      const supported =
        typeof window !== "undefined" &&
        "PublicKeyCredential" in window &&
        navigator.credentials != null &&
        typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === "function" &&
        (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().catch(() => false));
      if (!active) return;
      setWebauthnSupported(supported);
      setBiometricLabel(/Mac|iPhone|iPad/.test(navigator.platform) ? "Touch ID" : "Passkey");
    }
    checkWebAuthn();
    return () => {
      active = false;
    };
  }, []);

  function resetAuthFeedback(nextMode: AuthMode) {
    setAuthMode(nextMode);
    setStatus("idle");
    setError("");
    setPassword("");
    setConfirmPassword("");
  }

  function persistRememberedIdentifier(email: string) {
    if (rememberEmail) localStorage.setItem(rememberedIdentifierKey, email);
    else localStorage.removeItem(rememberedIdentifierKey);
  }

  function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedIdentifier = identifier.trim().toLowerCase();
    setError("");
    setStatus("idle");
    if (!normalizedIdentifier) {
      setError("Enter an email or the demo username.");
      return;
    }
    if (!password) {
      setError("Enter a password.");
      passwordRef.current?.focus();
      return;
    }

    if (authMode === "signup") {
      const validationError = validateSignup(normalizedIdentifier, password, confirmPassword);
      if (validationError) {
        setError(validationError);
        return;
      }
      const accounts = readDemoAccounts();
      const exists =
        normalizedIdentifier === demoCredential.email ||
        accounts.some((account) => account.email.toLowerCase() === normalizedIdentifier);
      if (exists) {
        setError("An account with that email already exists. Switch to sign in.");
        return;
      }
      const account = { email: normalizedIdentifier, password, createdAt: new Date().toISOString() };
      writeDemoAccounts([...accounts, account]);
      persistRememberedIdentifier(account.email);
      setStatus("success");
      onAuthenticated(createSession("password", account.email));
      return;
    }

    const localAccount = readDemoAccounts().find((account) => account.email.toLowerCase() === normalizedIdentifier);
    const demoMatch = [demoCredential.email, demoCredential.username].includes(normalizedIdentifier) && password === demoCredential.password;
    const accountMatch = localAccount?.password === password;
    if (!demoMatch && !accountMatch) {
      setError("These credentials do not match any local demo account.");
      return;
    }
    const sessionEmail = demoMatch ? demoCredential.email : localAccount?.email ?? normalizedIdentifier;
    persistRememberedIdentifier(sessionEmail);
    setStatus("success");
    onAuthenticated(createSession("password", sessionEmail));
  }

  async function signInWithPasskey() {
    if (!webauthnSupported) return;
    setStatus("checking");
    setError("");
    try {
      const storedCredentialId = localStorage.getItem(passkeyStorageKey);
      if (storedCredentialId) {
        await navigator.credentials.get({
          publicKey: {
            challenge: randomChallenge(),
            allowCredentials: [{ id: base64UrlToBuffer(storedCredentialId), type: "public-key" }],
            userVerification: "required",
            timeout: 60_000,
          },
        });
      } else {
        const credential = await navigator.credentials.create({
          publicKey: {
            challenge: randomChallenge(),
            rp: { name: "Belem Capital Demo" },
            user: {
              id: new TextEncoder().encode(demoUserId),
              name: demoCredential.email,
              displayName: "DeFi Contagion Demo",
            },
            pubKeyCredParams: [
              { type: "public-key", alg: -7 },
              { type: "public-key", alg: -257 },
            ],
            authenticatorSelection: {
              authenticatorAttachment: "platform",
              residentKey: "preferred",
              userVerification: "required",
            },
            attestation: "none",
            timeout: 60_000,
          },
        });
        if (!credential || !("rawId" in credential)) throw new Error("No passkey was created.");
        localStorage.setItem(passkeyStorageKey, bufferToBase64Url((credential as PublicKeyCredential).rawId));
      }
      setStatus("success");
      onAuthenticated(createSession("webauthn", demoCredential.email));
    } catch {
      setStatus("error");
      setError(`${biometricLabel} sign-in was cancelled or is not available. Use the demo password instead.`);
    }
  }

  return (
    <main className="auth-shell">
      <motion.section
        className="auth-panel"
        aria-labelledby="auth-title"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="auth-topline">
          <div className="brand-mark compact" aria-hidden="true">
            <DeFiLogo compact />
          </div>
          <button className="mode-toggle" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label="Toggle theme">
            {theme === "light" ? <Sun size={14} /> : <Moon size={14} />}
            {theme}
          </button>
        </div>

        <div className="auth-heading">
          <p className="eyebrow">Belem Capital</p>
          <h1 id="auth-title">DeFi Contagion</h1>
          <p className="lead">
            {authMode === "signin"
              ? "Sign in to inspect dependency risk, scenario loss and exit decisions from the offline fixture portfolio."
              : "Create a local prototype account for this browser, then enter the dashboard without a backend."}
          </p>
        </div>

        <div className="auth-switch" role="tablist" aria-label="Authentication mode">
          <button type="button" role="tab" aria-selected={authMode === "signin"} onClick={() => resetAuthFeedback("signin")}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={authMode === "signup"} onClick={() => resetAuthFeedback("signup")}>
            Create account
          </button>
        </div>

        <form className="auth-form" onSubmit={submitPassword} noValidate>
          <label className="field-label" htmlFor="demo-identifier">
            {authMode === "signin" ? "Account" : "Email"}
          </label>
          <input
            id="demo-identifier"
            autoComplete="username"
            type={authMode === "signup" ? "email" : "text"}
            value={identifier}
            onChange={(event) => {
              setIdentifier(event.target.value);
              setError("");
            }}
            aria-invalid={Boolean(error && !identifier.trim())}
          />

          <label className="field-label" htmlFor="demo-password">
            Password
          </label>
          <div className="password-field">
            <input
              id="demo-password"
              ref={passwordRef}
              type={showPassword ? "text" : "password"}
              autoComplete={authMode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              aria-invalid={Boolean(error)}
              aria-describedby="auth-feedback auth-demo-note"
            />
            <button type="button" className="icon-button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>

          {authMode === "signup" ? (
            <>
              <label className="field-label" htmlFor="demo-confirm-password">
                Confirm password
              </label>
              <input
                id="demo-confirm-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => {
                  setConfirmPassword(event.target.value);
                  setError("");
                }}
                aria-invalid={Boolean(error && password !== confirmPassword)}
                aria-describedby="auth-feedback auth-demo-note"
              />
            </>
          ) : null}

          <div className="auth-row">
            <label className="check-row">
              <input type="checkbox" checked={rememberEmail} onChange={(event) => setRememberEmail(event.target.checked)} />
              <span>Remember email only</span>
            </label>
            <span className="demo-credential">{demoCredential.email} / demo</span>
          </div>

          <button className="run-button auth-submit" type="submit">
            {authMode === "signin" ? "Sign in" : "Create account"}
          </button>
        </form>

        {authMode === "signin" ? (
          <>
            <div className="auth-divider">
              <span>or</span>
            </div>

            <button
              className="biometric-button"
              type="button"
              onClick={signInWithPasskey}
              disabled={!webauthnSupported || status === "checking"}
              aria-describedby="auth-demo-note"
            >
              <Fingerprint size={17} />
              {status === "checking" ? `Waiting for ${biometricLabel}` : `Sign in with ${biometricLabel}`}
            </button>
          </>
        ) : null}

        <div className="auth-feedback" id="auth-feedback" aria-live="polite">
          {error ? <p role="alert">{error}</p> : null}
          {status === "success" ? <p>{authMode === "signin" ? "Signed in." : "Account created."} Opening the dashboard.</p> : null}
          {authMode === "signin" && !webauthnSupported ? <p>{biometricLabel} is not available here; password sign-in is ready.</p> : null}
        </div>

        <p className="auth-note" id="auth-demo-note">
          Prototype authentication only. Use {demoCredential.email} or username {demoCredential.username} with password {demoCredential.password}, or create a local account saved in this browser. Login sessions are never persisted after reload.
        </p>
      </motion.section>
    </main>
  );
}

function createSession(method: AuthSession["method"], email: string): AuthSession {
  return { email, method, signedInAt: new Date().toISOString() };
}

function validateSignup(email: string, password: string, confirmPassword: string) {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "Enter a valid email address.";
  if (password.length < 6) return "Use at least 6 characters for the prototype password.";
  if (password !== confirmPassword) return "Passwords do not match.";
  return "";
}

function readDemoAccounts(): LocalDemoAccount[] {
  if (typeof window === "undefined") return [];
  const raw = localStorage.getItem(accountsStorageKey);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (account): account is LocalDemoAccount =>
        typeof account?.email === "string" && typeof account?.password === "string" && typeof account?.createdAt === "string",
    );
  } catch {
    localStorage.removeItem(accountsStorageKey);
    return [];
  }
}

function writeDemoAccounts(accounts: LocalDemoAccount[]) {
  localStorage.setItem(accountsStorageKey, JSON.stringify(accounts));
}

function clearStoredSession() {
  localStorage.removeItem(sessionStorageKey);
  sessionStorage.removeItem(sessionStorageKey);
}

function randomChallenge() {
  const challenge = new Uint8Array(32);
  crypto.getRandomValues(challenge);
  return challenge;
}

function bufferToBase64Url(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBuffer(value: string) {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

function Sidebar({
  view,
  setView,
  mode,
  setMode,
  theme,
  setTheme,
  health,
  onSignOut,
  session,
}: {
  view: View;
  setView: (view: View) => void;
  mode: DataMode;
  setMode: (mode: DataMode) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  health?: AppData["health"];
  onSignOut: () => void;
  session: AuthSession;
}) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({ Explore: true, Run: true });

  return (
    <aside className="sidebar">
      <div className="brand-mark" aria-hidden="true">
        <DeFiLogo />
      </div>

      <nav className="sidebar-nav" aria-label="Dashboard navigation">
        {sections.map((section) => (
          <div className="nav-section" key={section.label}>
            <button
              className="section-trigger"
              aria-expanded={openSections[section.label]}
              onClick={() => setOpenSections((current) => ({ ...current, [section.label]: !current[section.label] }))}
            >
              {section.label}
              <ChevronDown size={14} />
            </button>
            <AnimatePresence initial={false}>
              {openSections[section.label] ? (
                <motion.div
                  className="section-menu"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                >
                  {section.items.map((item) => {
                    const Icon = viewMeta[item].icon;
                    return (
                      <button key={item} className="nav-item" data-selected={view === item} onClick={() => setView(item)}>
                        <Icon size={15} />
                        {viewMeta[item].label}
                      </button>
                    );
                  })}
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        ))}
      </nav>

      <div className="sidebar-controls">
        <span className="status-line">Signed in as {session.email}</span>
        <button className="mode-toggle" onClick={() => setMode(mode === "fixture" ? "api" : "fixture")} aria-pressed={mode === "fixture"}>
          <Database size={14} />
          {mode === "fixture" ? "Fixtures ON" : "Live API"}
        </button>
        <button className="mode-toggle" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
          {theme === "light" ? <Sun size={14} /> : <Moon size={14} />}
          {theme}
        </button>
        <button className="mode-toggle" onClick={onSignOut}>
          <LogOut size={14} />
          Sign out
        </button>
        {health?.mockedFixtures.length ? <span className="status-line">{health.mockedFixtures.length} mock</span> : null}
      </div>
    </aside>
  );
}

function PortfolioDashboard({
  data,
  selectedPosition,
  setSelectedPosition,
  setView,
  hoveredPosition,
  setHoveredPosition,
}: {
  data: AppData;
  selectedPosition: string;
  setSelectedPosition: (id: string) => void;
  setView: (view: View) => void;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("net_equity_usd");
  const filtered = useMemo(() => {
    return [...data.portfolio.positions]
      .filter((position) => filter === "all" || position.protocol === filter)
      .sort((a, b) => {
        if (sortKey === "protocol") return a.protocol.localeCompare(b.protocol);
        return Number(b[sortKey]) - Number(a[sortKey]);
      });
  }, [data.portfolio.positions, filter, sortKey]);
  const selectedPortfolio = data.portfolio.positions.find((position) => position.position_id === selectedPosition) ?? data.portfolio.positions[0];
  const selectedRisk = data.risk.positions.find((item) => item.position_id === selectedPortfolio.position_id);
  const selectedSource = selectedRisk?.source_type ?? selectedPortfolio.data_origin;
  const peerPositions = data.portfolio.positions.filter((position) => position.position_id !== selectedPortfolio.position_id);

  return (
    <motion.div className="page-stack" initial="hidden" animate="show" variants={staggerGroup}>
      <SummaryStrip
        portfolio={data.portfolio}
        risk={data.risk}
        analytics={data.analytics}
        analyticsIsPreset={data.analyticsIsPreset}
        selectedPosition={selectedPortfolio.position_id}
        hoveredPosition={hoveredPosition}
        setHoveredPosition={setHoveredPosition}
      />
      <motion.section className="position-master-detail" aria-label="Position selector" variants={riseItem}>
        <motion.article
          key={selectedPortfolio.position_id}
          className="position-detail-card"
          data-selected="true"
          data-highlighted={hoveredPosition === selectedPortfolio.position_id}
          style={{ ["--stress-pct" as string]: stressShare(selectedPortfolio, selectedRisk) }}
          layout
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          onMouseEnter={() => setHoveredPosition(selectedPortfolio.position_id)}
          onMouseLeave={() => setHoveredPosition(null)}
        >
          <div className="position-detail-copy">
            <div className="card-topline">
              <span className="node-chip" data-type="position" />
              <strong>{selectedPortfolio.protocol}</strong>
              <Badge tone={sourceTone(selectedSource)}>{selectedSource}</Badge>
            </div>
            <h2>{compactId(selectedPortfolio.position_id)}</h2>
            <p>{labelize(selectedPortfolio.position_type)}</p>
          </div>
          <div className="position-detail-metrics">
            <MetricPair label="Gross" value={money(selectedPortfolio.gross_value_usd)} />
            <MetricPair label="Debt" value={money(selectedPortfolio.debt_value_usd)} />
            <MetricPair label="Net equity" value={money(selectedPortfolio.net_equity_usd)} />
          </div>
          <div className="detail-loss-strip">
            <span>Stress loss under active scenario</span>
            <strong>{money(selectedRisk?.conditional_loss_usd)}</strong>
          </div>
          <button className="icon-button text-button" onClick={() => setView("decision")}>
            <ArrowUpDown size={14} />
            Open decision view
          </button>
        </motion.article>

        <div className="position-card-stack">
          {peerPositions.map((position, index) => {
          const risk = data.risk.positions.find((item) => item.position_id === position.position_id);
          const source = risk?.source_type ?? position.data_origin;
          return (
            <motion.button
              key={position.position_id}
              className="position-card position-card--compact"
              data-selected="false"
              data-highlighted={hoveredPosition === position.position_id}
              style={{ ["--stress-pct" as string]: stressShare(position, risk) }}
              data-tooltip={`Select ${compactId(position.position_id)} as the active position.`}
              aria-label={`Select ${compactId(position.position_id)}`}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24, delay: index * 0.04, ease: [0.22, 1, 0.36, 1] }}
              onMouseEnter={() => setHoveredPosition(position.position_id)}
              onMouseLeave={() => setHoveredPosition(null)}
              onFocus={() => setHoveredPosition(position.position_id)}
              onBlur={() => setHoveredPosition(null)}
              onClick={() => setSelectedPosition(position.position_id)}
            >
              <div className="card-topline">
                <span className="node-chip" data-type="position" />
                <strong>{position.protocol}</strong>
                <Badge tone={sourceTone(source)}>{source}</Badge>
              </div>
              <h2>{compactId(position.position_id)}</h2>
              <p>{labelize(position.position_type)}</p>
              <MetricPair label="Gross" value={money(position.gross_value_usd)} />
              <MetricPair label="Debt" value={money(position.debt_value_usd)} />
              <MetricPair label="Net equity" value={money(position.net_equity_usd)} />
              <div className="loss-strip">
                <span>stress loss</span>
                <strong>{money(risk?.conditional_loss_usd)}</strong>
              </div>
            </motion.button>
          );
        })}
        </div>
      </motion.section>

      <motion.section className="table-panel" variants={riseItem}>
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Sortable portfolio table</p>
            <h2>Gross exposure and net equity stay separate</h2>
          </div>
          <div className="toolbar-row">
            <select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter protocol">
              <option value="all">All protocols</option>
              <option value="ethena">Ethena</option>
              <option value="aave">Aave</option>
              <option value="morpho">Morpho</option>
              <option value="pendle">Pendle</option>
            </select>
            <button className="icon-button text-button" onClick={() => setSortKey(sortKey === "net_equity_usd" ? "gross_value_usd" : "net_equity_usd")}>
              <ArrowUpDown size={14} />
              Sort
            </button>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Position</th>
              <th>Protocol</th>
              <th>Gross</th>
              <th>Debt</th>
              <th>Net equity</th>
              <th>Exit venue</th>
              <th>Data</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((position, index) => (
              <motion.tr
                key={position.position_id}
                data-selected={position.position_id === selectedPosition}
                data-highlighted={hoveredPosition === position.position_id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.22, delay: index * 0.035, ease: [0.22, 1, 0.36, 1] }}
                onMouseEnter={() => setHoveredPosition(position.position_id)}
                onMouseLeave={() => setHoveredPosition(null)}
                onClick={() => setSelectedPosition(position.position_id)}
              >
                <td>{compactId(position.position_id)}</td>
                <td>{position.protocol}</td>
                <td>{money(position.gross_value_usd)}</td>
                <td>{money(position.debt_value_usd)}</td>
                <td>{money(position.net_equity_usd)}</td>
                <td>{position.exit_venue_id}</td>
                <td>
                  <Badge tone="warn">{position.data_origin}</Badge>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
        <WarningList warnings={data.marketSnapshot.warnings} />
      </motion.section>
    </motion.div>
  );
}

function SummaryStrip({
  portfolio,
  risk,
  analytics,
  analyticsIsPreset,
  selectedPosition,
  hoveredPosition,
  setHoveredPosition,
}: {
  portfolio: Portfolio;
  risk: AppData["risk"];
  analytics: AppData["analytics"];
  analyticsIsPreset: boolean;
  selectedPosition: string;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
}) {
  const headline = analytics?.headline;
  const tenPctNav = analytics?.breaking_points.nav_drawdown.find((row) => Number(row.nav_drawdown_pct) === 0.1);
  const kpiMoney = (value: string | number | null | undefined) => {
    if (value === null || value === undefined) return "n/a";
    return `$${(Number(value) / 1_000_000).toFixed(2)}M`;
  };
  return (
    <motion.section className="summary-strip" variants={staggerGroup}>
      <Stat label="Gross exposure" value={kpiMoney(portfolio.totals.gross_value_usd)} detail="not capital" highlightId={selectedPosition} highlighted={hoveredPosition === selectedPosition} setHoveredPosition={setHoveredPosition} />
      <Stat label="Debt" value={kpiMoney(portfolio.totals.debt_value_usd)} detail="borrow liabilities" highlightId={selectedPosition} highlighted={hoveredPosition === selectedPosition} setHoveredPosition={setHoveredPosition} />
      <Stat label="Net equity" value={kpiMoney(portfolio.totals.net_equity_usd)} detail="capital at risk" highlightId={selectedPosition} highlighted={hoveredPosition === selectedPosition} setHoveredPosition={setHoveredPosition} />
      <Stat
        label="Conditional loss"
        value={kpiMoney(risk.portfolio.total_conditional_loss_usd)}
        detail={risk.portfolio.aggregation_status}
        highlightId={selectedPosition}
        highlighted={hoveredPosition === selectedPosition}
        setHoveredPosition={setHoveredPosition}
      />
      {headline ? (
        <>
          <Stat
            label="USDe effective leverage"
            value={`${Number(headline.usde_effective_leverage).toFixed(2)}×`}
            detail={`${money(headline.usde_exposure_usd)} on one factor`}
          />
          <Stat
            label="NAV −10% at"
            value={tenPctNav?.usde_depeg_pct ? percent(tenPctNav.usde_depeg_pct) : "n/a"}
            detail={tenPctNav?.usde_price ? `USDe depeg to ${Number(tenPctNav.usde_price).toFixed(3)}` : "not reached"}
          />
          <Stat label="Top risk driver" value={headline.top_risk_driver ?? "n/a"} detail="largest loss swing" valueKind="text" />
          <Stat
            label="Act if probability >"
            value={percent(headline.targeted_plan_break_even_probability)}
            detail={`targeted plan saves ${money(headline.derisking_savings_usd)}${analyticsIsPreset ? ` · at ${money(headline.scenario_loss_usd)} preset loss` : ""}`}
          />
        </>
      ) : null}
    </motion.section>
  );
}

function stressShare(position: PortfolioPosition, risk?: RiskPosition) {
  const gross = Number(position.gross_value_usd);
  const loss = Math.abs(Number(risk?.conditional_loss_usd ?? 0));
  if (!Number.isFinite(gross) || gross <= 0 || !Number.isFinite(loss)) return "0%";
  return `${Math.min(100, (loss / gross) * 100).toFixed(2)}%`;
}

function DependencyGraphView({
  graph,
  risk,
  scenario,
  selectedPosition,
  setSelectedPosition,
  selectedEdge,
  setSelectedEdge,
  hoveredPosition,
  setHoveredPosition,
}: {
  graph: DependencyGraph;
  risk: AppData["risk"];
  scenario: ScenarioKind;
  selectedPosition: string;
  setSelectedPosition: (id: string) => void;
  selectedEdge: GraphEdge | null;
  setSelectedEdge: (edge: GraphEdge | null) => void;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [enabledTypes, setEnabledTypes] = useState<Record<string, boolean>>({
    asset: true,
    protocol: true,
    market: true,
    oracle: true,
    position: true,
    venue: true,
  });
  const flow = useReactFlow();
  // Highlight the selected position's contagion paths, as computed by the risk engine for this scenario.
  const selectedContagion = risk.positions.find((position) => position.position_id === selectedPosition)?.contagion;
  const activePosition = hoveredPosition ?? selectedPosition;
  const activeContagion = risk.positions.find((position) => position.position_id === activePosition)?.contagion;
  const selectedEdges = useMemo(() => new Set(selectedContagion?.paths.flatMap((path) => path.edges) ?? []), [selectedContagion]);
  const activeEdges = useMemo(() => new Set(activeContagion?.paths.flatMap((path) => path.edges) ?? []), [activeContagion]);
  const activeNodeIds = useMemo(() => {
    const nodes = new Set(activeContagion?.paths.flatMap((path) => path.nodes) ?? []);
    nodes.add(`position:${activePosition}`);
    return nodes;
  }, [activeContagion, activePosition]);
  const layout = useMemo(() => layoutGraph(graph.nodes), [graph.nodes]);
  const nodeLabel = (id: string) => graph.nodes.find((node) => node.id === id)?.label ?? id;
  const visibleNodeIds = useMemo(() => {
    return new Set(
      graph.nodes
        .filter((node) => enabledTypes[node.type] !== false)
        .filter((node) => `${node.id} ${node.label}`.toLowerCase().includes(search.toLowerCase()))
        .map((node) => node.id),
    );
  }, [enabledTypes, graph.nodes, search]);

  const focusIsActive = activeNodeIds.size > 0;
  const flowNodes = useMemo<Node[]>(() => {
    return graph.nodes
      .filter((node) => visibleNodeIds.has(node.id))
      .map((node) => ({
        id: node.id,
        position: layout[node.id] ?? { x: 160, y: 160 },
        data: {
          label: (
            <motion.div
              layout
              className="flow-node"
              data-type={node.type}
              data-selected={node.id === `position:${selectedPosition}`}
              data-highlighted={node.id === `position:${hoveredPosition}`}
              data-active={activeNodeIds.has(node.id)}
              data-dimmed={focusIsActive && !activeNodeIds.has(node.id)}
              onClick={() => {
                if (node.id.startsWith("position:")) setSelectedPosition(node.id.replace("position:", ""));
              }}
              transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            >
              <span>{node.type}</span>
              <strong>{node.label}</strong>
            </motion.div>
          ),
        },
        draggable: true,
      }));
  }, [activeNodeIds, focusIsActive, graph.nodes, hoveredPosition, layout, selectedPosition, setSelectedPosition, visibleNodeIds]);

  const flowEdges = useMemo<Edge[]>(() => {
    return graph.edges
      .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
      .map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.relation,
        type: "smoothstep",
        animated: activeEdges.has(edge.id),
        className: `edge-${edge.confidence} ${activeEdges.has(edge.id) ? "edge-critical" : ""} ${selectedEdges.has(edge.id) ? "edge-selected" : ""}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 2,
        data: edge,
      }));
  }, [activeEdges, graph.edges, selectedEdges, visibleNodeIds]);

  const types = Array.from(new Set(graph.nodes.map((node) => node.type)));
  const flowKey = `${scenario}-${selectedPosition}-${hoveredPosition ?? "none"}-${search}-${types.map((type) => `${type}:${enabledTypes[type] !== false}`).join("|")}`;

  return (
    <div className="graph-layout">
      <section className="graph-stage">
        <ReactFlow
          key={flowKey}
          defaultNodes={flowNodes}
          defaultEdges={flowEdges}
          onEdgeClick={(_, edge) => setSelectedEdge(edge.data as GraphEdge)}
          onNodeClick={(_, node) => {
            if (node.id.startsWith("position:")) setSelectedPosition(node.id.replace("position:", ""));
          }}
          onNodeMouseEnter={(_, node) => {
            if (node.id.startsWith("position:")) setHoveredPosition(node.id.replace("position:", ""));
          }}
          onNodeMouseLeave={() => setHoveredPosition(null)}
          fitView
          minZoom={0.35}
          maxZoom={1.35}
        >
          <Background gap={28} size={1} color="var(--np-line-strong)" />
          <MiniMap pannable zoomable nodeColor={(node) => nodeTypeColor[(graph.nodes.find((item) => item.id === node.id) as GraphNode)?.type] ?? "var(--np-soft)"} />
          <Controls />
          <Panel position="top-left" className="flow-panel">
            <label className="search-field">
              <Search size={14} />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search node" />
            </label>
            <button className="icon-button text-button" onClick={() => flow.fitView({ duration: 420 })}>
              Fit view
            </button>
          </Panel>
        </ReactFlow>
      </section>

      <aside className="inspector-panel">
        <p className="eyebrow">Node filters</p>
        <div className="filter-chips">
          {types.map((type) => (
            <button
              key={type}
              className="filter-chip"
              data-active={enabledTypes[type] !== false}
              onClick={() => setEnabledTypes((current) => ({ ...current, [type]: current[type] === false }))}
            >
              <span className="node-chip" data-type={type} />
              {type}
            </button>
          ))}
        </div>

        <div className="divider" />
        <p className="eyebrow">Edge evidence</p>
        {selectedEdge ? (
          <div className="evidence-card">
            <h2>{labelize(selectedEdge.relation)}</h2>
            <Definition label="Risk channel" value={labelize(selectedEdge.risk_channel)} />
            <Definition label="Confidence" value={<Badge tone={confidenceTone[selectedEdge.confidence]}>{selectedEdge.confidence}</Badge>} />
            <Definition label="Method" value={labelize(selectedEdge.evidence.method)} />
            <Definition label="Reference" value={selectedEdge.evidence.reference} />
            <Definition label="Observed" value={selectedEdge.evidence.observed_at} />
          </div>
        ) : (
          <p className="muted">Click an edge to inspect relation, source and confidence.</p>
        )}

        <div className="divider" />
        <p className="eyebrow">Contagion paths · {compactId(selectedPosition)}</p>
        {selectedContagion?.paths.length ? (
          <div className="evidence-card">
            {selectedContagion.paths.map((path) => (
              <Definition
                key={`${path.factor}-${path.edges.join("-")}`}
                label={labelize(path.factor)}
                value={
                  <>
                    {path.nodes.map(nodeLabel).join(" → ")} <Badge tone={confidenceTone[path.confidence]}>{path.confidence}</Badge>
                  </>
                }
              />
            ))}
          </div>
        ) : (
          <p className="muted">No contagion path for this position in the current result.</p>
        )}
        <WarningList warnings={[...(selectedContagion?.graph_gaps ?? []), ...(selectedContagion?.unmodeled_exposures ?? [])]} />

        {risk.contagion?.hubs.length ? (
          <>
            <div className="divider" />
            <p className="eyebrow">Contagion hubs</p>
            <div className="evidence-card">
              {risk.contagion.hubs.slice(0, 5).map((hub) => (
                <Definition
                  key={hub.node}
                  label={hub.label}
                  value={`${hub.positions.length} positions · ${money(hub.net_equity_usd)} net equity`}
                />
              ))}
            </div>
          </>
        ) : null}
        <WarningList warnings={graph.warnings ?? []} />
      </aside>
    </div>
  );
}

function ScenarioLab({
  data,
  scenario,
  setScenario,
  selectedPosition,
  setSelectedPosition,
  hoveredPosition,
  setHoveredPosition,
  shockPct,
  setShockPct,
  horizonDays,
  setHorizonDays,
  liquidityLossPct,
  setLiquidityLossPct,
  extraInputs,
  setExtraInput,
  runScenario,
}: {
  data: AppData;
  scenario: ScenarioKind;
  setScenario: (scenario: ScenarioKind) => void;
  selectedPosition: string;
  setSelectedPosition: (id: string) => void;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
  shockPct: number;
  setShockPct: (value: number) => void;
  horizonDays: number;
  setHorizonDays: (value: number) => void;
  liquidityLossPct: number;
  setLiquidityLossPct: (value: number) => void;
  extraInputs: ExtraInputs;
  setExtraInput: <K extends keyof ExtraInputs>(key: K, value: ExtraInputs[K]) => void;
  runScenario: () => void;
}) {
  const selectedRisk = data.risk.positions.find((position) => position.position_id === selectedPosition) ?? data.risk.positions[0];
  // Real engine results for the current sliders (API: live; offline: precomputed surface).
  const valuationData = data.risk.positions.map((position) => ({
    id: position.position_id,
    name: compactId(position.position_id),
    before: Number(position.net_equity_before_usd),
    after: Number(position.net_equity_after_usd),
  }));
  const controls = scenarioControls[scenario];
  // node_shock prices these node kinds; oracles and venues belong to other scenarios.
  const shockableNodes = data.graph.nodes.filter((node) => ["asset", "protocol", "market", "offchain_entity"].includes(node.type));
  const nodeLabel = (id: string) => data.graph.nodes.find((node) => node.id === id)?.label ?? id;
  const sourceCopy = {
    engine: "Live risk engine result for the current inputs.",
    surface: "Risk engine results precomputed for the main slider (offline mode).",
    fixture: "Static fixture result: inputs are not applied.",
  }[data.riskSource];
  const ignoredCopy = data.ignoredInputs.length
    ? ` Offline, ${data.ignoredInputs.map(labelize).join(", ")} stay at the preset; switch to Live API to apply them.`
    : "";

  return (
    <div className="scenario-layout">
      <section className="preset-grid">
        {scenarioOrder.map((kind) => (
          <button key={kind} className="preset-card" data-selected={scenario === kind} onClick={() => setScenario(kind)}>
            <span>{scenarioCopy[kind].preset}</span>
            <strong>{scenarioCopy[kind].title}</strong>
            <p>{scenarioCopy[kind].summary}</p>
          </button>
        ))}
      </section>

      <section className="control-panel">
        {controls.includes("shock") ? (
          <Control label="USDe shock magnitude" value={signedPercent(-shockPct)}>
            <input type="range" min="1" max="40" value={shockPct} onChange={(event) => setShockPct(Number(event.target.value))} />
          </Control>
        ) : null}
        {controls.includes("liquidity") ? (
          <Control label="Liquidity depth reduction" value={`${liquidityLossPct}%`}>
            <input type="range" min="0" max="95" value={liquidityLossPct} onChange={(event) => setLiquidityLossPct(Number(event.target.value))} />
          </Control>
        ) : null}
        {controls.includes("ltShift") ? (
          <Control label="Liquidation threshold shift" value={`${extraInputs.ltShiftPct > 0 ? "+" : ""}${extraInputs.ltShiftPct} pts`}>
            <input
              type="range"
              min="-15"
              max="5"
              value={extraInputs.ltShiftPct}
              onChange={(event) => setExtraInput("ltShiftPct", Number(event.target.value))}
            />
          </Control>
        ) : null}
        {controls.includes("carry") ? (
          <>
            <Control label="Borrow APY on all debt" value={`${extraInputs.borrowApyPct}%`}>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={extraInputs.borrowApyPct}
                onChange={(event) => setExtraInput("borrowApyPct", Number(event.target.value))}
              />
            </Control>
            <Control label="sUSDe staking APY" value={`${extraInputs.susdeApyPct}%`}>
              <input
                type="range"
                min="-10"
                max="15"
                value={extraInputs.susdeApyPct}
                onChange={(event) => setExtraInput("susdeApyPct", Number(event.target.value))}
              />
            </Control>
          </>
        ) : null}
        {controls.includes("node") ? (
          <>
            <Control label="Failing node" value={nodeLabel(extraInputs.nodeId)}>
              <select value={extraInputs.nodeId} onChange={(event) => setExtraInput("nodeId", event.target.value)} aria-label="Failing node">
                {shockableNodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.label}
                  </option>
                ))}
              </select>
            </Control>
            <Control label="Value lost at the node" value={`${extraInputs.nodeLossPct}%`}>
              <input
                type="range"
                min="0"
                max="50"
                step="5"
                value={extraInputs.nodeLossPct}
                onChange={(event) => setExtraInput("nodeLossPct", Number(event.target.value))}
              />
            </Control>
          </>
        ) : null}
        <Control label="Decision horizon" value={`${horizonDays} days`}>
          <input type="range" min="1" max="30" value={horizonDays} onChange={(event) => setHorizonDays(Number(event.target.value))} />
        </Control>
        <button className="run-card" onClick={runScenario}>
          <Play size={16} />
          Run risk engine
        </button>
      </section>

      <section className="visual-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Animated before / after</p>
            <h2>Net equity under stress</h2>
            <p className="microcopy">
              {sourceCopy}
              {ignoredCopy}
            </p>
          </div>
          <select value={selectedPosition} onChange={(event) => setSelectedPosition(event.target.value)} aria-label="Select position">
            {data.portfolio.positions.map((position) => (
              <option key={position.position_id} value={position.position_id}>
                {position.protocol}
              </option>
            ))}
          </select>
        </div>
        <div className="chart-frame">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={valuationData}
              onMouseMove={(state) => {
                const active = (state as { activePayload?: Array<{ payload?: { id?: string } }> }).activePayload?.[0]?.payload;
                if (active?.id) setHoveredPosition(active.id);
              }}
              onMouseLeave={() => setHoveredPosition(null)}
              onClick={(state) => {
                const active = (state as { activePayload?: Array<{ payload?: { id?: string } }> })?.activePayload?.[0]?.payload;
                if (active?.id) setSelectedPosition(active.id);
              }}
            >
              <CartesianGrid stroke="var(--np-line)" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(value) => money(value).replace(".00", "")} tickLine={false} axisLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="before" fill="var(--np-soft)" radius={[4, 4, 0, 0]}>
                {valuationData.map((entry) => (
                  <Cell key={`before-${entry.id}`} opacity={!hoveredPosition || hoveredPosition === entry.id ? 1 : 0.28} />
                ))}
              </Bar>
              <Bar dataKey="after" fill="var(--np-strong)" radius={[4, 4, 0, 0]}>
                {valuationData.map((entry) => (
                  <Cell key={`after-${entry.id}`} opacity={!hoveredPosition || hoveredPosition === entry.id ? 1 : 0.28} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="gauge-panel">
        <div>
          <p className="eyebrow">Liquidation metric</p>
          <h2>{selectedRisk.risk_metric ? labelize(selectedRisk.risk_metric.type) : "No lending metric"}</h2>
          <p>Liquidatable does not mean fully liquidated; it means the protocol threshold has been breached.</p>
        </div>
        {selectedRisk.risk_metric ? <RiskGauge metric={selectedRisk.risk_metric} /> : <p className="muted">Token holdings and PT holdings do not have HF/LTV thresholds.</p>}
      </section>

      {data.risk.comparison ? (
        <section className="gauge-panel">
          <div>
            <p className="eyebrow">What this scenario adds</p>
            <h2>{data.risk.comparison.excess_loss_usd !== null ? money(data.risk.comparison.excess_loss_usd) : "n/a"}</h2>
            <p>{data.risk.comparison.excess_meaning}</p>
          </div>
          <div className="evidence-card">
            <Definition label="This scenario" value={money(data.risk.portfolio.total_conditional_loss_usd)} />
            {data.risk.comparison.runs.map((run) => (
              <Definition key={run.run_id} label={run.description} value={money(run.total_conditional_loss_usd)} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function DecisionEngine({
  data,
  scenario,
  scenarioInputs,
  hasRun,
  selectedRisk,
  selectedPortfolio,
  selectedPosition,
  setSelectedPosition,
  hoveredPosition,
  setHoveredPosition,
  inspectedExitFraction,
  setInspectedExitFraction,
  setView,
}: {
  data: AppData;
  scenario: ScenarioKind;
  scenarioInputs: ScenarioInputs;
  hasRun: boolean;
  selectedRisk?: RiskPosition;
  selectedPortfolio?: PortfolioPosition;
  selectedPosition: string;
  setSelectedPosition: (id: string) => void;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
  inspectedExitFraction: string | null;
  setInspectedExitFraction: (fraction: string | null) => void;
  setView: (view: View) => void;
}) {
  if (!hasRun || !selectedRisk || !selectedPortfolio) {
    return <EmptyState title="No scenario result yet" detail="Run the scenario lab to populate the decision engine." />;
  }

  const costData = data.decision.exit_options.map((option) => ({
    fraction: option.exit_fraction,
    exit: percent(option.exit_fraction, 0),
    cost: Number(option.estimated_exit_cost_usd),
    residual: Number(option.residual_stress_loss_usd),
    breakEven: option.break_even_probability ? Number(option.break_even_probability) * 100 : null,
  }));
  const inspectedOption = inspectedExitFraction ? data.decision.exit_options.find((item) => item.exit_fraction === inspectedExitFraction) : null;

  return (
    <motion.div className="decision-layout" initial="hidden" animate="show" variants={staggerGroup}>
      <motion.section className="decision-main" variants={riseItem}>
        <div className="selector-row">
          {data.portfolio.positions.map((position) => (
            <button
              key={position.position_id}
              className="mini-tab"
              data-selected={position.position_id === selectedPosition}
              data-highlighted={hoveredPosition === position.position_id}
              onMouseEnter={() => setHoveredPosition(position.position_id)}
              onMouseLeave={() => setHoveredPosition(null)}
              onClick={() => setSelectedPosition(position.position_id)}
            >
              {position.protocol}
            </button>
          ))}
        </div>

        <section className="impact-strip">
          <Stat label="Before" value={money(selectedRisk.net_equity_before_usd)} detail={labelize(selectedPortfolio.position_type)} highlighted={hoveredPosition === selectedPosition} />
          <Stat label="After" value={money(selectedRisk.net_equity_after_usd)} detail={scenarioCopy[scenario].title} highlighted={hoveredPosition === selectedPosition} />
          <Stat label="Conditional loss" value={money(selectedRisk.conditional_loss_usd)} detail={selectedRisk.calculation_status} highlighted={hoveredPosition === selectedPosition} />
        </section>

        <section className="visual-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Exit cost curve</p>
              <h2>Cost vs residual stress loss</h2>
            </div>
            <Badge tone="warn">assumption-driven</Badge>
          </div>
          <div className="chart-frame decision-chart-frame">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={costData}
                onMouseMove={(state) => {
                  const active = (state as { activePayload?: Array<{ payload?: { fraction?: string } }> })?.activePayload?.[0]?.payload;
                  if (active?.fraction) setInspectedExitFraction(active.fraction);
                }}
                onClick={(state) => {
                  const active = (state as { activePayload?: Array<{ payload?: { fraction?: string } }> })?.activePayload?.[0]?.payload;
                  if (active?.fraction) setInspectedExitFraction(active.fraction);
                }}
              >
                <CartesianGrid stroke="var(--np-line)" vertical={false} />
                <XAxis dataKey="exit" tickLine={false} axisLine={false} />
                <YAxis tickFormatter={(value) => money(value)} tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Line
                  type="monotone"
                  dataKey="cost"
                  stroke="var(--np-accent-coral)"
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 1.5 }}
                  activeDot={{ r: 6, strokeWidth: 2 }}
                />
                <Line
                  type="monotone"
                  dataKey="residual"
                  stroke="var(--np-strong)"
                  strokeWidth={2}
                  strokeDasharray="4 5"
                  dot={{ r: 3, strokeWidth: 1.5 }}
                  activeDot={{ r: 6, strokeWidth: 2 }}
                />
                <Brush dataKey="exit" height={18} stroke="var(--np-strong)" travellerWidth={8} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="table-panel">
          <table>
            <thead>
              <tr>
                <th>Exit</th>
                <th>Cost</th>
                <th>Residual loss</th>
                <th>Foregone yield</th>
                <th>Break-even</th>
                <th>Quote</th>
              </tr>
            </thead>
            <tbody>
              {data.decision.exit_options.map((option) => (
                <tr
                  key={option.exit_fraction}
                  data-selected={inspectedExitFraction === option.exit_fraction}
                  onMouseEnter={() => setInspectedExitFraction(option.exit_fraction)}
                  onMouseLeave={() => setInspectedExitFraction(null)}
                  onClick={() => setInspectedExitFraction(option.exit_fraction)}
                >
                  <td>{percent(option.exit_fraction, 0)}</td>
                  <td>{money(option.estimated_exit_cost_usd)}</td>
                  <td>{money(option.residual_stress_loss_usd)}</td>
                  <td>{money(option.foregone_yield_usd)}</td>
                  <td>{option.break_even_probability ? percent(option.break_even_probability, 2) : "stay"}</td>
                  <td>
                    <Badge tone="warn">{option.quote_status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </motion.section>

      <motion.aside className="decision-inspector" variants={riseItem}>
        <div className="verdict">
          <BadgeCheck size={18} />
          <div>
            <span>Verdict</span>
            <strong>{data.decision.recommendation}</strong>
          </div>
        </div>
        <p>{data.decision.reason}</p>
        <div className="scenario-receipt" aria-label="Scenario inputs used for the latest run">
          <MetricPair label="Scenario" value={scenarioCopy[scenario].title} />
          {/* Only the inputs this scenario actually uses. */}
          {scenarioControls[scenario].includes("shock") ? <MetricPair label="USDe shock" value={signedPercent(-scenarioInputs.shockPct)} /> : null}
          {scenarioControls[scenario].includes("liquidity") ? <MetricPair label="Liquidity loss" value={`${scenarioInputs.liquidityLossPct}%`} /> : null}
          {scenarioControls[scenario].includes("ltShift") ? <MetricPair label="LT shift" value={`${scenarioInputs.ltShiftPct} pts`} /> : null}
          {scenarioControls[scenario].includes("carry") ? (
            <>
              <MetricPair label="Borrow APY" value={`${scenarioInputs.borrowApyPct}%`} />
              <MetricPair label="sUSDe APY" value={`${scenarioInputs.susdeApyPct}%`} />
            </>
          ) : null}
          {scenarioControls[scenario].includes("node") ? (
            <MetricPair label="Node shock" value={`${labelize(scenarioInputs.nodeId)} -${scenarioInputs.nodeLossPct}%`} />
          ) : null}
          <MetricPair label="Horizon" value={`${scenarioInputs.horizonDays} days`} />
        </div>
        <button className="icon-button text-button" onClick={() => setView("graph")}>
          <GitBranch size={14} />
          Inspect causal path
        </button>
        <div className="divider" />
        {inspectedExitFraction ? (
          <div className="inspect-callout">
            <p className="eyebrow">Inspected exit</p>
            <h2>{percent(inspectedExitFraction, 0)}</h2>
            <p>
              {inspectedOption
                ? `${money(inspectedOption.estimated_exit_cost_usd)} immediate cost, ${money(inspectedOption.residual_stress_loss_usd)} residual stress loss.`
                : "No fixture row for this exit fraction."}
            </p>
          </div>
        ) : null}
        <p className="eyebrow">Loss breakdown</p>
        {Object.entries(selectedRisk.loss_components).map(([key, value]) => (
          <MetricPair key={key} label={labelize(key)} value={money(value)} />
        ))}
        <WarningList warnings={[...selectedRisk.warnings, ...data.decision.warnings]} />
      </motion.aside>
    </motion.div>
  );
}

function CommandPalette({
  open,
  query,
  setQuery,
  setOpen,
  data,
  executeAction,
}: {
  open: boolean;
  query: string;
  setQuery: (query: string) => void;
  setOpen: (open: boolean) => void;
  data?: AppData;
  executeAction: (action: DashboardAction) => void;
}) {
  const commands = createActionRegistry(data).filter((command) => command.label.toLowerCase().includes(query.toLowerCase()));
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    itemRefs.current[highlightedIndex]?.scrollIntoView({ block: "nearest" });
  }, [highlightedIndex, open]);

  function runCommand(index: number) {
    const command = commands[index];
    if (!command) return;
    command.actions.forEach(executeAction);
    setOpen(false);
    setQuery("");
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((current) => Math.min(current + 1, Math.max(commands.length - 1, 0)));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((current) => Math.max(current - 1, 0));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runCommand(highlightedIndex);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  }

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="command-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <motion.div
            className="command-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            onKeyDown={handleKeyDown}
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="command-search">
              <Search size={15} />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Jump to page or position"
                aria-label="Search commands"
                aria-controls="command-results"
                aria-activedescendant={commands[highlightedIndex] ? `command-${highlightedIndex}` : undefined}
              />
              <button onClick={() => setOpen(false)} aria-label="Close command palette">
                <X size={15} />
              </button>
            </div>
            <div className="command-list" id="command-results" role="listbox" aria-label="Command results">
              {commands.map((command, index) => (
                <button
                  key={`${command.type}-${command.label}`}
                  id={`command-${index}`}
                  ref={(element) => {
                    itemRefs.current[index] = element;
                  }}
                  role="option"
                  aria-selected={index === highlightedIndex}
                  data-highlighted={index === highlightedIndex}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  onClick={() => runCommand(index)}
                >
                  <span>{command.type}</span>
                  {command.label}
                </button>
              ))}
              {!commands.length ? <p className="command-empty">No command matches that search.</p> : null}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function AssistantDock({
  open,
  setOpen,
  stateData,
  mode,
  view,
  scenario,
  selectedPosition,
  inspectedExitFraction,
  scenarioInputs,
  executeAction,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  stateData: AppData;
  mode: DataMode;
  view: View;
  scenario: ScenarioKind;
  selectedPosition: string;
  inspectedExitFraction: string | null;
  scenarioInputs: ScenarioInputs;
  executeAction: (action: DashboardAction) => void;
}) {
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      content: "Ask about the selected position, dependency evidence, scenario loss, or an exit fraction. I only use the results on screen.",
    },
  ]);
  const [input, setInput] = useState("");
  const [assistantState, setAssistantState] = useState<AssistantState>("idle");
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(() => typeof window !== "undefined" && Boolean(window.SpeechRecognition ?? window.webkitSpeechRecognition));
  const [voiceIssue, setVoiceIssue] = useState("");
  const [voiceDiagnostic, setVoiceDiagnostic] = useState("");
  const [amplitude, setAmplitude] = useState(0.12);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recognitionFinalRef = useRef(false);
  const recognitionTranscriptRef = useRef("");
  const recognitionActiveRef = useRef(false);
  const recognitionWantedRef = useRef(false);
  const recognitionManualStopRef = useRef(false);
  const recognitionHadErrorRef = useRef(false);
  const recognitionRestartCountRef = useRef(0);
  const amplitudeIntervalRef = useRef<number | null>(null);
  const speechRunRef = useRef(0);
  const activeSpeechMessageRef = useRef<string | null>(null);
  const speechUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const submitMessageRef = useRef<(raw: string, inputMode?: AssistantInputMode) => void>(() => undefined);
  const latestAssistantMessage = useMemo(() => [...messages].reverse().find((message) => message.role === "assistant"), [messages]);

  useEffect(() => {
    setVoiceSupported(Boolean(window.SpeechRecognition ?? window.webkitSpeechRecognition));
  }, []);

  useEffect(() => {
    if (!open) return;
    messagesEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, assistantState, voiceIssue, voiceDiagnostic, open]);

  useEffect(() => {
    if (!open) return;
    const first = panelRef.current?.querySelector<HTMLElement>("input, button");
    first?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeAssistant();
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusables = Array.from(panelRef.current.querySelectorAll<HTMLElement>("button, input, textarea, [tabindex]:not([tabindex='-1'])")).filter(
        (element) => !element.hasAttribute("disabled"),
      );
      const firstFocusable = focusables[0];
      const lastFocusable = focusables[focusables.length - 1];
      if (!firstFocusable || !lastFocusable) return;
      if (event.shiftKey && document.activeElement === firstFocusable) {
        event.preventDefault();
        lastFocusable.focus();
      } else if (!event.shiftKey && document.activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, setOpen]);

  useEffect(() => {
    return () => {
      stopListening();
      cancelSpeech();
    };
  }, []);

  async function submitMessage(raw: string, inputMode: AssistantInputMode = "text") {
    const trimmed = raw.trim();
    if (!trimmed) return;
    cancelSpeech();
    setInput("");
    const userMessage: AssistantMessage = { id: crypto.randomUUID(), role: "user", content: trimmed, inputMode };
    setMessages((current) => [...current, userMessage]);
    setAssistantState("thinking");
    try {
      const response = await postAssistantMessage(
        {
          message: trimmed,
          view,
          scenario,
          selectedPosition,
          inspectedExitFraction,
          scenarioInputs,
          data: stateData,
        },
        mode,
      );
      const assistantMessage: AssistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.message?.trim() || "The assistant returned an empty reply. Check the backend logs for the raw model response.",
        inputMode,
      };
      console.info("[Assistant UI] assistant reply received", response);
      setMessages((current) => [...current, assistantMessage]);
      if (response.actions?.length) {
        for (const action of response.actions) {
          executeAction(action);
          await new Promise((resolve) => window.setTimeout(resolve, action.type === "run_simulation" ? 520 : 300));
        }
      }
      setAssistantState("idle");
    } catch (error) {
      console.warn("[Assistant UI] assistant request failed", error);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "The assistant could not answer. It runs in the browser from the results on screen; try rephrasing.",
        },
      ]);
      setAssistantState("idle");
    }
  }
  submitMessageRef.current = submitMessage;

  function cancelSpeech() {
    speechRunRef.current += 1;
    if ("speechSynthesis" in window) {
      console.info("[Assistant speech] cancel", {
        pending: window.speechSynthesis.pending,
        speaking: window.speechSynthesis.speaking,
      });
      window.speechSynthesis.cancel();
    }
    speechUtteranceRef.current = null;
    if (activeSpeechMessageRef.current) {
      const messageId = activeSpeechMessageRef.current;
      setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, caption: undefined } : message)));
      activeSpeechMessageRef.current = null;
    }
    setAssistantState((current) => (current === "speaking" ? "idle" : current));
  }

  async function speak(text: string, messageId: string) {
    const cleanText = text.replace(/\s+/g, " ").trim();
    console.info("[Assistant speech] speaker requested", {
      messageId,
      characters: cleanText.length,
      supported: "speechSynthesis" in window,
    });
    if (!("speechSynthesis" in window)) {
      setVoiceIssue("Spoken replies are not supported in this browser.");
      setAssistantState("idle");
      return;
    }
    if (!cleanText) {
      console.warn("[Assistant speech] no text to speak");
      setVoiceIssue("There is no readable assistant reply yet.");
      setAssistantState("idle");
      return;
    }
    setVoiceIssue("");
    const synth = window.speechSynthesis;
    if (synth.speaking || synth.pending) {
      console.info("[Assistant speech] clearing existing speech queue before manual playback", {
        pending: synth.pending,
        speaking: synth.speaking,
      });
      synth.cancel();
    }
    const runId = speechRunRef.current + 1;
    speechRunRef.current = runId;
    activeSpeechMessageRef.current = messageId;
    setAssistantState("speaking");
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, caption: cleanText } : message)));

    const englishVoice = await resolveEnglishSpeechVoice(synth);
    if (speechRunRef.current !== runId) return;

    const sentences = splitSpeechSentences(cleanText);
    const speakSentence = (index: number) => {
      if (speechRunRef.current !== runId) return;
      const sentence = sentences[index];
      if (!sentence) {
        console.info("[Assistant speech] playback ended");
        setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, caption: undefined } : message)));
        activeSpeechMessageRef.current = null;
        speechUtteranceRef.current = null;
        setAssistantState("idle");
        return;
      }
      const utterance = new SpeechSynthesisUtterance(sentence);
      speechUtteranceRef.current = utterance;
      utterance.lang = "en-US";
      if (englishVoice) utterance.voice = englishVoice;
      utterance.rate = 0.96;
      utterance.pitch = 1;
      utterance.onstart = () => {
        if (speechRunRef.current !== runId) return;
        console.info("[Assistant speech] playback sentence started", { index, sentence });
        setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, caption: sentence } : message)));
        setAssistantState("speaking");
      };
      utterance.onend = () => speakSentence(index + 1);
      utterance.onerror = (event) => {
        if (speechRunRef.current !== runId) return;
        console.warn("[Assistant speech] playback error", event);
        setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, caption: undefined } : message)));
        activeSpeechMessageRef.current = null;
        speechUtteranceRef.current = null;
        setVoiceIssue(`The browser stopped spoken playback (${event.error}). Try pressing the speaker again.`);
        setAssistantState("idle");
      };
      synth.speak(utterance);
    };
    if (synth.paused) synth.resume();
    console.info("[Assistant speech] invoking speechSynthesis.speak", {
      pending: synth.pending,
      speaking: synth.speaking,
      paused: synth.paused,
      voice: englishVoice ? `${englishVoice.name} (${englishVoice.lang})` : "no English voice available; using lang=en-US",
      sentences: sentences.length,
    });
    speakSentence(0);
  }

  function speakLatestReply() {
    console.info("[Assistant speech] speaker button pressed", {
      hasLatestReply: Boolean(latestAssistantMessage),
      currentState: assistantState,
    });
    if (assistantState === "speaking") {
      cancelSpeech();
      return;
    }
    if (!latestAssistantMessage) {
      setVoiceIssue("There is no assistant reply to read yet.");
      return;
    }
    speak(latestAssistantMessage.content, latestAssistantMessage.id);
  }

  function closeAssistant() {
    stopListening();
    cancelSpeech();
    setOpen(false);
  }

  async function startListening() {
    if (recognitionWantedRef.current || recognitionActiveRef.current) {
      console.info("[Assistant voice] start ignored: recognition is already active");
      return;
    }
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceSupported(false);
      setVoiceIssue("Speech recognition is not supported in this browser. Chrome on localhost or HTTPS is supported.");
      setVoiceDiagnostic("SpeechRecognition API unavailable in this browser.");
      console.warn("[Assistant voice] SpeechRecognition unavailable", getSpeechRecognitionSupport());
      return;
    }
    setVoiceSupported(true);
    const supportSnapshot = getSpeechRecognitionSupport();
    console.info("[Assistant voice] support check", {
      standard: supportSnapshot.standard,
      webkit: supportSnapshot.webkit,
      secureContext: window.isSecureContext,
      protocol: window.location.protocol,
      host: window.location.host,
      hasMediaDevices: Boolean(navigator.mediaDevices?.getUserMedia),
      hasPermissionsApi: Boolean(navigator.permissions?.query),
    });
    setVoiceDiagnostic(`Voice input: ${supportSnapshot.engine}. Checking microphone permission...`);
    setVoiceIssue("");
    cancelSpeech();
    setListening(true);
    setAssistantState("listening");
    recognitionFinalRef.current = false;
    recognitionTranscriptRef.current = "";
    recognitionHadErrorRef.current = false;
    recognitionManualStopRef.current = false;
    recognitionRestartCountRef.current = 0;
    recognitionWantedRef.current = true;
    try {
      await confirmMicrophonePermission();
    } catch (error) {
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setListening(false);
        setAssistantState("idle");
        recognitionWantedRef.current = false;
        setVoiceIssue("Microphone permission was denied. Allow microphone access for this localhost page, then try again.");
        setVoiceDiagnostic("Microphone permission denied.");
        return;
      }
      if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        setListening(false);
        setAssistantState("idle");
        recognitionWantedRef.current = false;
        setVoiceIssue("No microphone was found. Connect or enable a microphone, then try again.");
        setVoiceDiagnostic("No microphone device was found.");
        return;
      }
      setListening(false);
      setAssistantState("idle");
      recognitionWantedRef.current = false;
      setVoiceIssue(`Microphone permission could not be confirmed (${name || "unknown"}). Typing still works.`);
      setVoiceDiagnostic(`Microphone check failed: ${name || "unknown"}.`);
      return;
    }

    setVoiceDiagnostic("Microphone permission granted. Starting speech recognition...");
    startAmbientListeningMotion();
    beginSpeechRecognition(Recognition);
  }

  async function confirmMicrophonePermission() {
    if (!window.isSecureContext && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
      console.warn("[Assistant voice] insecure context blocks microphone", {
        protocol: window.location.protocol,
        host: window.location.host,
      });
      throw new DOMException("Microphone requires HTTPS or localhost.", "SecurityError");
    }
    if (navigator.permissions?.query) {
      try {
        const permission = await navigator.permissions.query({ name: "microphone" as PermissionName });
        console.info("[Assistant voice] navigator.permissions microphone", { state: permission.state });
        setVoiceDiagnostic(`Microphone permission state: ${permission.state}. Requesting access...`);
      } catch (error) {
        console.info("[Assistant voice] navigator.permissions microphone query unavailable", error);
        setVoiceDiagnostic("Microphone permission API unavailable. Requesting access directly...");
      }
    } else {
      console.info("[Assistant voice] navigator.permissions API unavailable");
      setVoiceDiagnostic("Microphone permission API unavailable. Requesting access directly...");
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      console.warn("[Assistant voice] navigator.mediaDevices.getUserMedia unavailable");
      throw new DOMException("getUserMedia is unavailable in this environment.", "NotSupportedError");
    }
    console.info("[Assistant voice] requesting getUserMedia({ audio: true })");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    console.info("[Assistant voice] getUserMedia granted", {
      audioTracks: stream.getAudioTracks().map((track) => ({
        enabled: track.enabled,
        id: track.id,
        label: track.label,
        muted: track.muted,
        readyState: track.readyState,
      })),
    });
    // Chrome's SpeechRecognition owns the real capture. Holding this stream open
    // can make recognition abort immediately on some systems.
    stream.getTracks().forEach((track) => track.stop());
  }

  function beginSpeechRecognition(Recognition: SpeechRecognitionCtor) {
    if (!recognitionWantedRef.current || recognitionActiveRef.current) return;
    const recognition = getOrCreateSpeechRecognition(Recognition);
    console.info("[Assistant voice] calling SpeechRecognition.start()", {
      active: recognitionActiveRef.current,
      wanted: recognitionWantedRef.current,
      lang: recognition.lang,
      continuous: recognition.continuous,
      interimResults: recognition.interimResults,
    });
    try {
      recognition.start();
    } catch (error) {
      recognitionWantedRef.current = false;
      recognitionActiveRef.current = false;
      setListening(false);
      setAssistantState("idle");
      stopAmbientListeningMotion();
      console.warn("[Assistant voice] SpeechRecognition start failed", error);
      setVoiceIssue("Speech recognition could not start. It may already be running in this tab.");
      setVoiceDiagnostic("Speech recognition start failed before listening.");
    }
  }

  function getOrCreateSpeechRecognition(Recognition: SpeechRecognitionCtor) {
    if (recognitionRef.current) return recognitionRef.current;
    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onstart = () => {
      recognitionActiveRef.current = true;
      recognitionHadErrorRef.current = false;
      setListening(true);
      setAssistantState("listening");
      setVoiceIssue("");
      setVoiceDiagnostic("Speech recognition is listening...");
      console.info("[Assistant voice] SpeechRecognition started");
    };
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join(" ")
        .trim();
      recognitionTranscriptRef.current = transcript;
      console.info("[Assistant voice] SpeechRecognition result", {
        transcript,
        resultCount: event.results.length,
        isFinal: event.results[event.results.length - 1]?.isFinal,
      });
      setInput(transcript);
      setVoiceDiagnostic(transcript ? `Heard: "${transcript}"` : "Listening...");
      const last = event.results[event.results.length - 1];
      if (last?.isFinal && transcript) {
        recognitionFinalRef.current = true;
        recognitionWantedRef.current = false;
        recognitionManualStopRef.current = true;
        submitMessageRef.current(transcript, "voice");
        recognition.stop();
      }
    };
    recognition.onend = () => {
      recognitionActiveRef.current = false;
      const transcript = recognitionTranscriptRef.current.trim();
      console.info("[Assistant voice] SpeechRecognition ended", {
        wanted: recognitionWantedRef.current,
        final: recognitionFinalRef.current,
        hadError: recognitionHadErrorRef.current,
        manualStop: recognitionManualStopRef.current,
        transcript,
      });
      if (!recognitionFinalRef.current && !recognitionHadErrorRef.current && !recognitionManualStopRef.current && transcript) {
        recognitionFinalRef.current = true;
        recognitionWantedRef.current = false;
        submitMessageRef.current(transcript, "voice");
      } else if (!recognitionFinalRef.current && !recognitionHadErrorRef.current && !recognitionManualStopRef.current) {
        setVoiceIssue("Speech recognition ended without a transcript. Check microphone input, keep the tab focused, then try again.");
        setVoiceDiagnostic("Speech recognition ended with no transcript.");
      }
      recognitionWantedRef.current = false;
      setListening(false);
      if (!recognitionFinalRef.current) setAssistantState("idle");
      stopAmbientListeningMotion();
    };
    recognition.onerror = (event) => {
      const error = event.error ?? "unknown";
      recognitionHadErrorRef.current = true;
      console.warn("[Assistant voice] SpeechRecognition error", {
        error,
        event,
        wanted: recognitionWantedRef.current,
        active: recognitionActiveRef.current,
        manualStop: recognitionManualStopRef.current,
      });
      setVoiceDiagnostic(`Speech recognition error: ${error}.`);
      if (error === "not-allowed" || error === "service-not-allowed") {
        recognitionWantedRef.current = false;
        setVoiceIssue("Microphone permission was denied or blocked by the browser/OS. Allow microphone access for Chrome and this localhost page.");
      } else if (error === "no-speech") {
        setVoiceIssue("I did not catch speech. Try again, speak after the mic switches on, or type the request.");
      } else if (error === "audio-capture") {
        recognitionWantedRef.current = false;
        setVoiceIssue("The browser could not capture microphone audio. Check the selected input device and browser/OS permission.");
      } else if (error === "network") {
        recognitionWantedRef.current = false;
        setVoiceIssue("Speech recognition could not reach the browser speech service. Typing still works.");
      } else if (error === "aborted") {
        if (!recognitionManualStopRef.current) {
          setVoiceIssue("Speech recognition was aborted by the browser. Check tab focus, mic permission, and whether another app is holding the microphone.");
        }
      } else {
        setVoiceIssue(`Speech recognition stopped (${error}). Typing still works.`);
      }
    };
    recognitionRef.current = recognition;
    console.info("[Assistant voice] SpeechRecognition instance created", {
      lang: recognition.lang,
      continuous: recognition.continuous,
      interimResults: recognition.interimResults,
    });
    return recognition;
  }

  function stopListening() {
    recognitionWantedRef.current = false;
    recognitionManualStopRef.current = true;
    try {
      recognitionRef.current?.stop();
    } catch {
      recognitionRef.current?.abort?.();
    }
    recognitionActiveRef.current = false;
    stopAmbientListeningMotion();
    setListening(false);
    setAssistantState("idle");
    setAmplitude(0.12);
  }

  function startAmbientListeningMotion() {
    stopAmbientListeningMotion();
    let phase = 0;
    amplitudeIntervalRef.current = window.setInterval(() => {
      phase += 0.28;
      setAmplitude(0.22 + Math.abs(Math.sin(phase)) * 0.18);
    }, 120);
  }

  function stopAmbientListeningMotion() {
    if (amplitudeIntervalRef.current) window.clearInterval(amplitudeIntervalRef.current);
    amplitudeIntervalRef.current = null;
  }

  return (
    <>
      <button
        className="assistant-orb-button"
        data-state={assistantState}
        data-open={open}
        onClick={() => (open ? closeAssistant() : setOpen(true))}
        aria-label={open ? "Close assistant" : "Open assistant"}
      >
        <AssistantOrb state={assistantState} amplitude={amplitude} />
      </button>
      <AnimatePresence>
        {open ? (
          <motion.aside
            className="assistant-panel"
            data-state={assistantState}
            role="dialog"
            aria-modal="true"
            aria-label="DeFi Contagion assistant"
            ref={panelRef}
            initial={{ opacity: 0, y: 18, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.98 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="assistant-header">
              <div>
                <p className="eyebrow">Assistant</p>
                <h2>Ask from visible data</h2>
              </div>
              <button className="icon-button" onClick={closeAssistant} aria-label="Close assistant">
                <X size={15} />
              </button>
            </header>
            <div className="assistant-messages" aria-live="polite" ref={messagesRef}>
              {messages.map((message) => (
                <div className="assistant-message" data-role={message.role} key={message.id}>
                  <p>{message.content}</p>
                  {message.caption && message.role === "assistant" ? <small>{message.caption}</small> : null}
                </div>
              ))}
              {assistantState === "thinking" ? (
                <div className="assistant-message assistant-message-pending" data-role="assistant">
                  <p>Thinking with the local model...</p>
                </div>
              ) : null}
              {!voiceSupported ? <p className="speech-fallback">Voice input is not supported in this browser; typing still works.</p> : null}
              {voiceDiagnostic ? <p className="speech-fallback">{voiceDiagnostic}</p> : null}
              {voiceIssue ? <p className="speech-fallback">{voiceIssue}</p> : null}
              <div ref={messagesEndRef} aria-hidden="true" />
            </div>
            <form
              className="assistant-input"
              onSubmit={(event) => {
                event.preventDefault();
                submitMessage(input, "text");
              }}
            >
              <button type="button" className="icon-button" onClick={listening ? stopListening : startListening} aria-label={listening ? "Stop listening" : "Start voice input"}>
                {listening ? <MicOff size={15} /> : <Mic size={15} />}
              </button>
              <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about Aave, exit cost, or the graph" />
              <button type="submit" className="icon-button" aria-label="Send message">
                <Send size={15} />
              </button>
              <button
                type="button"
                className="icon-button"
                onClick={speakLatestReply}
                aria-label={assistantState === "speaking" ? "Stop spoken reply" : "Read latest assistant reply aloud"}
                aria-pressed={assistantState === "speaking"}
              >
                {assistantState === "speaking" ? <VolumeX size={15} /> : <Volume2 size={15} />}
              </button>
            </form>
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </>
  );
}

function getSpeechRecognitionSupport() {
  const standard = typeof window !== "undefined" && Boolean(window.SpeechRecognition);
  const webkit = typeof window !== "undefined" && Boolean(window.webkitSpeechRecognition);
  return {
    standard,
    webkit,
    engine: standard ? "SpeechRecognition" : webkit ? "webkitSpeechRecognition" : "unavailable",
  };
}

async function resolveEnglishSpeechVoice(synth: SpeechSynthesis) {
  let voices = synth.getVoices();
  console.info("[Assistant speech] voices snapshot", {
    count: voices.length,
    english: voices.filter((voice) => voice.lang.toLowerCase().startsWith("en")).map((voice) => `${voice.name} (${voice.lang})`),
  });

  if (!voices.length) {
    voices = await new Promise<SpeechSynthesisVoice[]>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        synth.removeEventListener("voiceschanged", finish);
        resolve(synth.getVoices());
      };
      synth.addEventListener("voiceschanged", finish);
      window.setTimeout(finish, 800);
    });
  }

  const englishVoice = pickEnglishSpeechVoice(voices);
  console.info("[Assistant speech] English voice resolution", {
    count: voices.length,
    selected: englishVoice ? `${englishVoice.name} (${englishVoice.lang})` : "none",
    englishCount: voices.filter((voice) => voice.lang.toLowerCase().startsWith("en")).length,
  });
  return englishVoice;
}

function pickEnglishSpeechVoice(voices: SpeechSynthesisVoice[]) {
  const englishVoices = voices.filter((voice) => voice.lang.toLowerCase().startsWith("en"));
  return [...englishVoices].sort((a, b) => naturalVoiceScore(b) - naturalVoiceScore(a))[0] ?? null;
}

function naturalVoiceScore(voice: SpeechSynthesisVoice) {
  const name = voice.name.toLowerCase();
  const lang = voice.lang.toLowerCase();
  let score = 0;
  if (lang.startsWith("en-us")) score += 80;
  else if (lang.startsWith("en-gb")) score += 70;
  else if (lang.startsWith("en")) score += 45;
  if (name.includes("google")) score += 130;
  if (name.includes("microsoft")) score += 125;
  if (name.includes("samantha")) score += 120;
  if (name.includes("natural")) score += 70;
  if (name.includes("neural")) score += 70;
  if (name.includes("premium")) score += 45;
  if (!voice.localService) score += 20;
  if (name.includes("compact") || name.includes("robot")) score -= 60;
  return score;
}

function splitSpeechSentences(text: string) {
  return text
    .replace(/\s+/g, " ")
    .split(/(?<=[.!?])\s+|;\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .flatMap((sentence) => {
      if (sentence.length <= 210) return [sentence];
      return sentence.split(/,\s+/).reduce<string[]>((chunks, clause) => {
        const last = chunks[chunks.length - 1];
        if (!last || `${last}, ${clause}`.length > 190) chunks.push(clause);
        else chunks[chunks.length - 1] = `${last}, ${clause}`;
        return chunks;
      }, []);
    });
}

function AssistantOrb({ state, amplitude }: { state: AssistantState; amplitude: number }) {
  const scale = 1 + amplitude * 0.12;
  const shimmer = state === "thinking" ? 1 : state === "speaking" ? 0.74 : state === "listening" ? 0.52 : 0.22;
  return (
    <svg className="assistant-orb" viewBox="0 0 120 120" aria-hidden="true" style={{ ["--orb-scale" as string]: scale, ["--orb-shimmer" as string]: shimmer }}>
      <defs>
        <filter id="orb-soften">
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.6" />
        </filter>
        <linearGradient id="orb-ink" x1="20%" x2="85%" y1="10%" y2="90%">
          <stop offset="0%" stopColor="var(--np-surface)" />
          <stop offset="42%" stopColor="var(--np-accent)" />
          <stop offset="100%" stopColor="var(--np-strong)" />
        </linearGradient>
      </defs>
      <motion.path
        filter="url(#orb-soften)"
        fill="url(#orb-ink)"
        animate={{
          d: [
            "M60 8C82 7 109 26 110 56C111 86 88 112 58 112C28 112 9 88 10 59C11 30 38 9 60 8Z",
            "M58 9C88 7 109 32 106 62C103 92 82 110 55 111C28 112 8 84 13 55C18 27 35 11 58 9Z",
            "M60 8C82 7 109 26 110 56C111 86 88 112 58 112C28 112 9 88 10 59C11 30 38 9 60 8Z",
          ],
          scale,
        }}
        transition={{ duration: state === "listening" ? 0.7 : 5.8, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.circle cx="72" cy="36" r="13" fill="color-mix(in srgb, var(--np-page) 76%, transparent)" animate={{ opacity: [0.24, 0.58, 0.24], x: [0, -8, 0] }} transition={{ duration: 3.6, repeat: Infinity }} />
      <motion.path
        d="M35 67C48 76 72 75 88 61"
        fill="none"
        stroke="color-mix(in srgb, var(--np-page) 72%, transparent)"
        strokeLinecap="round"
        strokeWidth="3"
        animate={{ pathLength: [0.25, 1, 0.25], opacity: [0.2, shimmer, 0.2] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
      />
      <Sparkles className="orb-icon" size={18} />
    </svg>
  );
}

function Control({ label, value, children }: { label: string; value: string; children: React.ReactNode }) {
  return (
    <label className="control-row">
      <span>{label}</span>
      <strong>{value}</strong>
      {children}
    </label>
  );
}

function RiskGauge({ metric }: { metric: NonNullable<RiskPosition["risk_metric"]> }) {
  const after = Number(metric.distance_to_liquidation_after_pct);
  return (
    <div className="risk-gauge">
      <div className="gauge-track">
        <span className="threshold" />
        <span className="gauge-fill" style={{ width: `${Math.max(6, Math.min(100, after * 100))}%` }} />
      </div>
      <div className="metric-row">
        <span>
          {metric.before} {"->"} {metric.after}
        </span>
        <Badge tone={metric.liquidatable ? "risk" : "good"}>{metric.liquidatable ? "liquidatable" : "not liquidatable"}</Badge>
      </div>
      <p className="muted">Threshold: {metric.threshold}. Distance after shock: {percent(after)}.</p>
    </div>
  );
}

function AnimatedHeading({ text }: { text: string }) {
  const prefersReducedMotion = usePrefersReducedMotion();
  if (prefersReducedMotion) return <h1>{text}</h1>;
  let letterIndex = 0;
  return (
    <h1 aria-label={text} className="reveal-heading">
      {text.split(" ").map((word, wordIndex) => (
        <span className="reveal-word" aria-hidden="true" key={`${word}-${wordIndex}`}>
          {word.split("").map((letter) => {
            const index = letterIndex;
            letterIndex += 1;
            return (
              <motion.span
                key={`${letter}-${index}`}
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.34, delay: index * 0.018, ease: easeOut }}
              >
                {letter}
              </motion.span>
            );
          })}
          {wordIndex < text.split(" ").length - 1 ? "\u00A0" : null}
        </span>
      ))}
    </h1>
  );
}

function Stat({
  label,
  value,
  detail,
  valueKind = "figure",
  highlightId,
  highlighted = false,
  setHoveredPosition,
}: {
  label: string;
  value: string;
  detail?: string;
  valueKind?: "figure" | "text";
  highlightId?: string;
  highlighted?: boolean;
  setHoveredPosition?: (id: string | null) => void;
}) {
  return (
    <motion.div
      className="stat"
      data-value-kind={valueKind}
      data-highlighted={highlighted}
      data-tooltip={detail ? `${label}: ${value}. ${detail}` : `${label}: ${value}`}
      variants={riseItem}
      onMouseEnter={() => {
        if (highlightId) setHoveredPosition?.(highlightId);
      }}
      onMouseLeave={() => {
        if (highlightId) setHoveredPosition?.(null);
      }}
    >
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{valueKind === "figure" ? <AnimatedFigure value={value} /> : value}</strong>
      <span className="stat-sublabel" aria-hidden="true" />
      {detail ? <small className="stat-footnote">{detail}</small> : <small className="stat-footnote" aria-hidden="true" />}
    </motion.div>
  );
}

function AnimatedFigure({ value }: { value: string }) {
  const parsed = useMemo(() => parseDisplayFigure(value), [value]);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [current, setCurrent] = useState(parsed?.amount ?? 0);

  useEffect(() => {
    if (!parsed) return;
    if (prefersReducedMotion) {
      setCurrent(parsed.amount);
      return;
    }
    const start = current;
    const end = parsed.amount;
    const startTime = window.performance.now();
    let frame = 0;
    const animate = (now: number) => {
      const progress = Math.min(1, (now - startTime) / 620);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCurrent(start + (end - start) * eased);
      if (progress < 1) frame = window.requestAnimationFrame(animate);
    };
    frame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frame);
  }, [parsed, prefersReducedMotion]);

  if (!parsed) return <>{value}</>;
  const formatted = parsed.grouped
    ? current.toLocaleString("en-US", { minimumFractionDigits: parsed.decimals, maximumFractionDigits: parsed.decimals })
    : current.toFixed(parsed.decimals);
  return (
    <span className="animated-figure" aria-label={value}>
      <span>{parsed.prefix}</span>
      <span>{formatted}</span>
      <span className="figure-unit">{parsed.suffix}</span>
    </span>
  );
}

function parseDisplayFigure(value: string) {
  const trimmed = value.trim();
  const match = trimmed.match(/^(\$)?(-?[\d,]+(?:\.\d+)?)(M|B|K|%|×)?$/);
  if (!match) return null;
  const numeric = match[2];
  const decimals = numeric.includes(".") ? numeric.split(".")[1].length : 0;
  return {
    prefix: match[1] ?? "",
    amount: Number(numeric.replace(/,/g, "")),
    suffix: match[3] ?? "",
    decimals,
    grouped: numeric.includes(","),
  };
}

function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(query.matches);
    const onChange = () => setPrefersReducedMotion(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return prefersReducedMotion;
}

function MetricPair({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-pair">
      <span>{label}</span>
      <strong>
        <AnimatedFigure value={value} />
      </strong>
    </div>
  );
}

function Badge({ children, tone = "neutral" }: { children: string; tone?: string }) {
  return <span className="badge" data-tone={tone}>{children}</span>;
}

function Definition({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="definition">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div className="warning-list">
      <AlertTriangle size={15} />
      <div>
        {warnings.map((warning) => (
          <p key={warning}>{warning}</p>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function SkeletonView() {
  return (
    <div className="skeleton-grid" aria-label="Loading">
      {Array.from({ length: 8 }).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

function ErrorView({ mode }: { mode: DataMode }) {
  return <EmptyState title="Data unavailable" detail={`The ${mode} data source did not respond. Switch back to fixture mode for the offline demo.`} />;
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <strong>{label}</strong>
      {payload.map((item) => (
        <span key={item.name}>
          {item.name}: {money(item.value)}
        </span>
      ))}
    </div>
  );
}

function sourceTone(source: string) {
  if (source === "observed" || source === "derived") return "good";
  if (source === "assumed" || source === "fictional" || source === "mock") return "warn";
  return "neutral";
}

export { App };
