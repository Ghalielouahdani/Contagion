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
  Mic,
  MicOff,
  GitBranch,
  Moon,
  Play,
  RefreshCw,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Volume2,
  WalletCards,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { loadAppData, marketSnapshot, postAssistantMessage } from "./data/api";
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
  ScenarioKind,
  View,
} from "./lib/types";

type Theme = "light" | "dark";
type SortKey = "protocol" | "gross_value_usd" | "debt_value_usd" | "net_equity_usd";
type AssistantState = "idle" | "listening" | "thinking" | "speaking";

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
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

const scenarioCopy = {
  usde_depeg: {
    title: "USDe depeg",
    preset: "-5% spot shock",
    summary: "USDe market price falls, affecting sUSDe, collateral valuation, PT pricing and liquidation distance.",
  },
  liquidity_crisis: {
    title: "Liquidity crisis",
    preset: "-80% exit depth",
    summary: "Reference marks can remain stable while executable exits degrade through thin shared venues.",
  },
};

const nodePositions: Record<string, { x: number; y: number }> = {
  "position:ethena_susde_01": { x: 40, y: 230 },
  "position:aave_01": { x: 40, y: 32 },
  "position:morpho_01": { x: 40, y: 410 },
  "asset:sUSDe": { x: 330, y: 250 },
  "asset:USDe": { x: 570, y: 250 },
  "protocol:ethena": { x: 830, y: 250 },
  "market:aave_01": { x: 330, y: 44 },
  "oracle:aave_01_usde": { x: 580, y: 44 },
  "protocol:aave": { x: 830, y: 44 },
  "venue:susde_usdc": { x: 330, y: 492 },
};

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
};

const sections = [
  { label: "Explore", items: ["portfolio", "graph"] as View[] },
  { label: "Run", items: ["scenario", "decision"] as View[] },
];

function App() {
  const [view, setView] = useState<View>("portfolio");
  const [scenario, setScenario] = useState<ScenarioKind>("usde_depeg");
  const [mode, setMode] = useState<DataMode>("fixture");
  const [theme, setTheme] = useState<Theme>("light");
  const [selectedPosition, setSelectedPosition] = useState("aave_01");
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [hoveredPosition, setHoveredPosition] = useState<string | null>(null);
  const [inspectedExitFraction, setInspectedExitFraction] = useState<string | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hasRun, setHasRun] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(false);

  const appQuery = useQuery({
    queryKey: ["app-data", mode, scenario],
    queryFn: () => loadAppData(mode, scenario),
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

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

  const data = appQuery.data;
  const selectedRisk = data?.risk.positions.find((position) => position.position_id === selectedPosition) ?? data?.risk.positions[0];
  const selectedPortfolio =
    data?.portfolio.positions.find((position) => position.position_id === selectedPosition) ?? data?.portfolio.positions[0];

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
    if (action.type === "select_scenario") {
      setScenario(action.scenario);
      if (action.run) runScenario();
    }
    if (action.type === "run_scenario") {
      if (action.scenario) setScenario(action.scenario);
      setHasRun(true);
      setView("decision");
    }
    if (action.type === "open_graph_for_position") {
      setSelectedPosition(action.positionId);
      setView("graph");
    }
    if (action.type === "inspect_exit_fraction") {
      setInspectedExitFraction(action.fraction);
      setView("decision");
    }
    if (action.type === "toggle_data_mode") setMode((current) => (current === "fixture" ? "api" : "fixture"));
    if (action.type === "toggle_theme") setTheme((current) => (current === "light" ? "dark" : "light"));
  }

  function reset() {
    setScenario("usde_depeg");
    setMode("fixture");
    setSelectedPosition("aave_01");
    setSelectedEdge(null);
    setHasRun(true);
    setView("portfolio");
  }

  return (
    <main className="app-shell">
      <Sidebar
        view={view}
        setView={setView}
        mode={mode}
        setMode={setMode}
        theme={theme}
        setTheme={setTheme}
        health={data?.health.status}
      />

      <section className="content-pane">
        <header className="topbar">
          <div>
            <p className="eyebrow">DeFi Contagion Explorer</p>
            <h1>{viewMeta[view].label}</h1>
            <p className="lead">{scenarioCopy[scenario].summary}</p>
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
                    setScenario={setScenario}
                    selectedPosition={selectedPosition}
                    setSelectedPosition={setSelectedPosition}
                    hoveredPosition={hoveredPosition}
                    setHoveredPosition={setHoveredPosition}
                    runScenario={runScenario}
                  />
                ) : null}
                {view === "decision" ? (
                  <DecisionEngine
                    data={data}
                    scenario={scenario}
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
        setView={setView}
        setSelectedPosition={setSelectedPosition}
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
          executeAction={executeAction}
        />
      ) : null}
    </main>
  );
}

function Sidebar({
  view,
  setView,
  mode,
  setMode,
  theme,
  setTheme,
  health,
}: {
  view: View;
  setView: (view: View) => void;
  mode: DataMode;
  setMode: (mode: DataMode) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  health?: string;
}) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({ Explore: true, Run: true });

  return (
    <aside className="sidebar">
      <div className="brand-mark" aria-hidden="true">
        <span />
        <span />
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
        <button className="mode-toggle" onClick={() => setMode(mode === "fixture" ? "api" : "fixture")}>
          <Database size={14} />
          {mode === "fixture" ? "Fixture mode" : "API mode"}
        </button>
        <button className="mode-toggle" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
          {theme === "light" ? <Sun size={14} /> : <Moon size={14} />}
          {theme}
        </button>
        <span className="status-line">{health ?? "loading"}</span>
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

  return (
    <div className="page-stack">
      <SummaryStrip portfolio={data.portfolio} risk={data.risk} />
      <section className="position-grid">
        {data.portfolio.positions.map((position) => {
          const risk = data.risk.positions.find((item) => item.position_id === position.position_id);
          const source = risk?.source_type ?? position.data_origin;
          return (
            <button
              key={position.position_id}
              className="position-card"
              data-selected={selectedPosition === position.position_id}
              data-highlighted={hoveredPosition === position.position_id}
              onMouseEnter={() => setHoveredPosition(position.position_id)}
              onMouseLeave={() => setHoveredPosition(null)}
              onClick={() => {
                setSelectedPosition(position.position_id);
                setView("decision");
              }}
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
            </button>
          );
        })}
      </section>

      <section className="table-panel">
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
            {filtered.map((position) => (
              <tr
                key={position.position_id}
                data-selected={position.position_id === selectedPosition}
                data-highlighted={hoveredPosition === position.position_id}
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
              </tr>
            ))}
          </tbody>
        </table>
        <WarningList warnings={marketSnapshot.warnings} />
      </section>
    </div>
  );
}

function SummaryStrip({ portfolio, risk }: { portfolio: Portfolio; risk: AppData["risk"] }) {
  return (
    <section className="summary-strip">
      <Stat label="Gross exposure" value={money(portfolio.totals.gross_value_usd)} detail="not capital" />
      <Stat label="Debt" value={money(portfolio.totals.debt_value_usd)} detail="borrow liabilities" />
      <Stat label="Net equity" value={money(portfolio.totals.net_equity_usd)} detail="capital at risk" />
      <Stat label="Conditional loss" value={money(risk.portfolio.total_conditional_loss_usd)} detail={risk.portfolio.aggregation_status} />
    </section>
  );
}

function DependencyGraphView({
  graph,
  scenario,
  selectedPosition,
  setSelectedPosition,
  selectedEdge,
  setSelectedEdge,
  hoveredPosition,
  setHoveredPosition,
}: {
  graph: DependencyGraph;
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
  const criticalEdges = scenario === "usde_depeg" ? new Set(["edge:1", "edge:2", "edge:3", "edge:4"]) : new Set(["edge:5", "edge:6"]);
  const visibleNodeIds = useMemo(() => {
    return new Set(
      graph.nodes
        .filter((node) => enabledTypes[node.type] !== false)
        .filter((node) => `${node.id} ${node.label}`.toLowerCase().includes(search.toLowerCase()))
        .map((node) => node.id),
    );
  }, [enabledTypes, graph.nodes, search]);

  const flowNodes = useMemo<Node[]>(() => {
    return graph.nodes
      .filter((node) => visibleNodeIds.has(node.id))
      .map((node) => ({
        id: node.id,
        position: nodePositions[node.id] ?? { x: 160, y: 160 },
        data: {
          label: (
            <div
              className="flow-node"
              data-type={node.type}
              data-selected={node.id === `position:${selectedPosition}`}
              data-highlighted={node.id === `position:${hoveredPosition}`}
              onClick={() => {
                if (node.id.startsWith("position:")) setSelectedPosition(node.id.replace("position:", ""));
              }}
            >
              <span>{node.type}</span>
              <strong>{node.label}</strong>
            </div>
          ),
        },
        draggable: true,
      }));
  }, [graph.nodes, selectedPosition, setSelectedPosition, visibleNodeIds]);

  const flowEdges = useMemo<Edge[]>(() => {
    return graph.edges
      .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
      .map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.relation,
        animated: criticalEdges.has(edge.id),
        className: `edge-${edge.confidence} ${criticalEdges.has(edge.id) ? "edge-critical" : ""}`,
        data: edge,
      }));
  }, [criticalEdges, graph.edges, visibleNodeIds]);

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
        <WarningList warnings={graph.warnings} />
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
  runScenario,
}: {
  data: AppData;
  scenario: ScenarioKind;
  setScenario: (scenario: ScenarioKind) => void;
  selectedPosition: string;
  setSelectedPosition: (id: string) => void;
  hoveredPosition: string | null;
  setHoveredPosition: (id: string | null) => void;
  runScenario: () => void;
}) {
  const [shock, setShock] = useState(5);
  const [horizon, setHorizon] = useState(7);
  const [liquidity, setLiquidity] = useState(80);
  const selectedRisk = data.risk.positions.find((position) => position.position_id === selectedPosition) ?? data.risk.positions[0];
  const previewScale = scenario === "usde_depeg" ? shock / 5 : liquidity / 80;
  const valuationData = data.risk.positions.map((position) => ({
    id: position.position_id,
    name: compactId(position.position_id),
    before: Number(position.net_equity_before_usd),
    after: Number(position.net_equity_before_usd) - Number(position.conditional_loss_usd) * previewScale,
  }));

  return (
    <div className="scenario-layout">
      <section className="preset-grid">
        {(["usde_depeg", "liquidity_crisis"] as ScenarioKind[]).map((kind) => (
          <button key={kind} className="preset-card" data-selected={scenario === kind} onClick={() => setScenario(kind)}>
            <span>{scenarioCopy[kind].preset}</span>
            <strong>{scenarioCopy[kind].title}</strong>
            <p>{scenarioCopy[kind].summary}</p>
          </button>
        ))}
      </section>

      <section className="control-panel">
        <Control label="USDe shock magnitude" value={signedPercent(-shock)}>
          <input type="range" min="1" max="25" value={shock} onChange={(event) => setShock(Number(event.target.value))} />
        </Control>
        <Control label="Liquidity depth reduction" value={`${liquidity}%`}>
          <input type="range" min="0" max="95" value={liquidity} onChange={(event) => setLiquidity(Number(event.target.value))} />
        </Control>
        <Control label="Decision horizon" value={`${horizon} days`}>
          <input type="range" min="1" max="30" value={horizon} onChange={(event) => setHorizon(Number(event.target.value))} />
        </Control>
        <button className="run-card" onClick={runScenario}>
          <Play size={16} />
          Run deterministic fixture
        </button>
      </section>

      <section className="visual-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Animated before / after</p>
            <h2>Net equity under stress</h2>
            <p className="microcopy">Fixture-scaled preview for slider interaction; canonical golden results stay in contracts/.</p>
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
    </div>
  );
}

function DecisionEngine({
  data,
  scenario,
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

  return (
    <div className="decision-layout">
      <section className="decision-main">
        <div className="selector-row">
          {data.portfolio.positions.map((position) => (
            <button
              key={position.position_id}
              className="mini-tab"
              data-selected={position.position_id === selectedPosition}
              onClick={() => setSelectedPosition(position.position_id)}
            >
              {position.protocol}
            </button>
          ))}
        </div>

        <section className="impact-strip">
          <Stat label="Before" value={money(selectedRisk.net_equity_before_usd)} detail={labelize(selectedPortfolio.position_type)} />
          <Stat label="After" value={money(selectedRisk.net_equity_after_usd)} detail={scenarioCopy[scenario].title} />
          <Stat label="Conditional loss" value={money(selectedRisk.conditional_loss_usd)} detail={selectedRisk.calculation_status} />
        </section>

        <section className="visual-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Exit cost curve</p>
              <h2>Cost vs residual stress loss</h2>
            </div>
            <Badge tone="warn">assumption-driven</Badge>
          </div>
          <div className="chart-frame">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={costData}
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
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
                <Line
                  type="monotone"
                  dataKey="residual"
                  stroke="var(--np-strong)"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
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
      </section>

      <aside className="decision-inspector">
        <div className="verdict">
          <BadgeCheck size={18} />
          <div>
            <span>Verdict</span>
            <strong>{scenario === "usde_depeg" ? data.decision.recommendation : "INSUFFICIENT_DATA"}</strong>
          </div>
        </div>
        <p>{scenario === "usde_depeg" ? data.decision.reason : "No P3 liquidity decision fixture yet. Showing risk and exit mechanics without inventing a recommendation."}</p>
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
              {(() => {
                const option = data.decision.exit_options.find((item) => item.exit_fraction === inspectedExitFraction);
                return option
                  ? `${money(option.estimated_exit_cost_usd)} immediate cost, ${money(option.residual_stress_loss_usd)} residual stress loss.`
                  : "No fixture row for this exit fraction.";
              })()}
            </p>
          </div>
        ) : null}
        <p className="eyebrow">Loss breakdown</p>
        {Object.entries(selectedRisk.loss_components).map(([key, value]) => (
          <MetricPair key={key} label={labelize(key)} value={money(value)} />
        ))}
        <WarningList warnings={[...selectedRisk.warnings, ...data.decision.warnings]} />
      </aside>
    </div>
  );
}

function CommandPalette({
  open,
  query,
  setQuery,
  setOpen,
  data,
  setView,
  setSelectedPosition,
  executeAction,
}: {
  open: boolean;
  query: string;
  setQuery: (query: string) => void;
  setOpen: (open: boolean) => void;
  data?: AppData;
  setView: (view: View) => void;
  setSelectedPosition: (id: string) => void;
  executeAction: (action: DashboardAction) => void;
}) {
  const commands = [
    ...Object.entries(viewMeta).map(([id, meta]) => ({ type: "page", label: meta.label, action: () => setView(id as View) })),
    { type: "scenario", label: "Run Scenario A - USDe depeg", action: () => executeAction({ type: "run_scenario", scenario: "usde_depeg" }) },
    { type: "scenario", label: "Run Scenario B - liquidity crisis", action: () => executeAction({ type: "run_scenario", scenario: "liquidity_crisis" }) },
    { type: "decision", label: "Inspect 50% exit", action: () => executeAction({ type: "inspect_exit_fraction", fraction: "0.50" }) },
    ...(data?.portfolio.positions.map((position) => ({
      type: "position",
      label: `${position.protocol} - ${compactId(position.position_id)}`,
      action: () => {
        executeAction({ type: "select_position", positionId: position.position_id, view: "decision" });
      },
    })) ?? []),
  ].filter((command) => command.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <AnimatePresence>
      {open ? (
        <motion.div className="command-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div
            className="command-panel"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="command-search">
              <Search size={15} />
              <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Jump to page or position" />
              <button onClick={() => setOpen(false)} aria-label="Close command palette">
                <X size={15} />
              </button>
            </div>
            <div className="command-list">
              {commands.map((command) => (
                <button
                  key={`${command.type}-${command.label}`}
                  onClick={() => {
                    command.action();
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <span>{command.type}</span>
                  {command.label}
                </button>
              ))}
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
  executeAction: (action: DashboardAction) => void;
}) {
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      content: "Ask about the selected position, dependency evidence, scenario loss, or an exit fraction. I only use the visible fixture data.",
    },
  ]);
  const [input, setInput] = useState("");
  const [assistantState, setAssistantState] = useState<AssistantState>("idle");
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [amplitude, setAmplitude] = useState(0.12);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    const first = panelRef.current?.querySelector<HTMLElement>("input, button");
    first?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
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
    return () => stopListening();
  }, []);

  async function submitMessage(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed) return;
    setInput("");
    const userMessage: AssistantMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
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
          data: stateData,
        },
        mode,
      );
      const assistantMessage: AssistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.message,
        action: response.action,
      };
      setMessages((current) => [...current, assistantMessage]);
      if (response.action) executeAction(response.action);
      speak(response.message);
    } catch {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "The assistant endpoint is unavailable. Fixture chat still works in fixture mode; API mode needs POST /api/v1/assistant.",
        },
      ]);
      setAssistantState("idle");
    }
  }

  function speak(text: string) {
    if (!("speechSynthesis" in window)) {
      setAssistantState("idle");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onstart = () => setAssistantState("speaking");
    utterance.onend = () => setAssistantState("idle");
    utterance.onerror = () => setAssistantState("idle");
    window.speechSynthesis.speak(utterance);
  }

  async function startListening() {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceSupported(false);
      return;
    }
    setVoiceSupported(true);
    setListening(true);
    setAssistantState("listening");
    try {
      const stream = await navigator.mediaDevices?.getUserMedia({ audio: true });
      if (stream) {
        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 128;
        source.connect(analyser);
        analyserRef.current = analyser;
        const values = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteFrequencyData(values);
          const avg = values.reduce((sum, value) => sum + value, 0) / values.length / 255;
          setAmplitude(Math.max(0.08, Math.min(1, avg * 1.8)));
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      }
    } catch {
      setAmplitude(0.28);
    }

    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join(" ");
      setInput(transcript);
      const last = event.results[event.results.length - 1];
      if (last?.isFinal) submitMessage(transcript);
    };
    recognition.onend = () => {
      setListening(false);
      setAssistantState("idle");
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    recognition.onerror = () => {
      setListening(false);
      setAssistantState("idle");
      setVoiceSupported(false);
    };
    recognitionRef.current = recognition;
    recognition.start();
  }

  function stopListening() {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setListening(false);
    setAssistantState("idle");
    setAmplitude(0.12);
  }

  return (
    <>
      <button className="assistant-orb-button" onClick={() => setOpen(!open)} aria-label={open ? "Close assistant" : "Open assistant"}>
        <AssistantOrb state={assistantState} amplitude={amplitude} />
      </button>
      <AnimatePresence>
        {open ? (
          <motion.aside
            className="assistant-panel"
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
              <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close assistant">
                <X size={15} />
              </button>
            </header>
            <div className="assistant-messages" aria-live="polite">
              {messages.map((message) => (
                <div className="assistant-message" data-role={message.role} key={message.id}>
                  <p>{message.content}</p>
                  {message.caption && message.role === "assistant" ? <small>{message.caption}</small> : null}
                </div>
              ))}
              {!voiceSupported ? <p className="speech-fallback">Voice is not available in this browser; typing still works.</p> : null}
            </div>
            <form
              className="assistant-input"
              onSubmit={(event) => {
                event.preventDefault();
                submitMessage(input);
              }}
            >
              <button type="button" className="icon-button" onClick={listening ? stopListening : startListening} aria-label={listening ? "Stop listening" : "Start voice input"}>
                {listening ? <MicOff size={15} /> : <Mic size={15} />}
              </button>
              <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about Aave, exit cost, or the graph" />
              <button type="submit" className="icon-button" aria-label="Send message">
                <Send size={15} />
              </button>
              <button type="button" className="icon-button" onClick={() => speak(messages[messages.length - 1]?.content ?? "")} aria-label="Read last reply aloud">
                <Volume2 size={15} />
              </button>
            </form>
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </>
  );
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
          <stop offset="0%" stopColor="var(--np-accent-periwinkle)" />
          <stop offset="36%" stopColor="var(--np-accent-lilac)" />
          <stop offset="70%" stopColor="var(--np-accent-coral)" />
          <stop offset="100%" stopColor="var(--np-accent-gold)" />
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
      <motion.circle cx="72" cy="36" r="13" fill="rgba(255,255,255,0.52)" animate={{ opacity: [0.28, 0.62, 0.28], x: [0, -8, 0] }} transition={{ duration: 3.6, repeat: Infinity }} />
      <motion.path
        d="M35 67C48 76 72 75 88 61"
        fill="none"
        stroke="rgba(255,255,255,0.72)"
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

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function MetricPair({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-pair">
      <span>{label}</span>
      <strong>{value}</strong>
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
