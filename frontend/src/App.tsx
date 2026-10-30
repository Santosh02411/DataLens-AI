import { Activity, Check, ChevronRight, Download, FileUp, FlaskConical, Gauge, LayoutDashboard, Lightbulb, MessageSquareText, Search, SlidersHorizontal, Table2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, browserEngine } from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { AskView } from "./components/AskView";
import { BuilderView } from "./components/BuilderView";
import { HealthView } from "./components/HealthView";
import { InvestigationView } from "./components/InvestigationView";
import { BenchmarkView } from "./components/BenchmarkView";
import { LiveDashboard } from "./components/LiveDashboard";
import { RecordExplorer } from "./components/RecordExplorer";
import { WhatIfView } from "./components/WhatIfView";
import { ThemeToggle } from "./ThemeContext";
import { InsightsView, TopInsights } from "./components/InsightsView";
import { Overview } from "./components/Overview";
import { ErrorNote, Spinner } from "./components/ui";
import { UploadScreen } from "./components/UploadScreen";
import type { AnalysisResult, DatasetSummary, InsightsResponse, Profile, Status, Suggestion } from "./types";

type View = "overview" | "insights" | "investigate" | "health" | "ask" | "whatif" | "builder" | "data" | "benchmark";

const NAV: { id: View; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "insights", label: "Insights", icon: Lightbulb },
  { id: "ask", label: "Ask", icon: MessageSquareText },
  { id: "whatif", label: "What-if", icon: FlaskConical },
  { id: "builder", label: "Build analysis", icon: SlidersHorizontal },
  { id: "data", label: "Data table", icon: Table2 },
  { id: "health", label: "Data health", icon: Activity },
  { id: "benchmark", label: "Benchmark", icon: Gauge },
];

const TITLES: Record<View, string> = {
  overview: "Overview",
  insights: "Data Detective",
  investigate: "Data Detective",
  whatif: "What-if simulator",
  benchmark: "Accuracy benchmark",
  health: "Data health",
  ask: "Ask a question",
  builder: "Build an analysis",
  data: "Data table",
};

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisResult[]>([]);
  const [builderResult, setBuilderResult] = useState<AnalysisResult | null>(null);
  const [view, setView] = useState<View>("overview");
  const [investigateId, setInvestigateId] = useState<string | null>(null);
  const [insights, setInsights] = useState<{ loading: boolean; error: unknown; data: InsightsResponse | null }>({ loading: false, error: null, data: null });

  const insightsFor = useRef<string | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    // Keep the active tab visible in the horizontally scrolling mobile nav.
    navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [view])
  const loadInsights = useCallback((id: string) => {
    insightsFor.current = id;  // ignore late responses for a dataset that's no longer open
    setInsights({ loading: true, error: null, data: null });
    api
      .insights(id)
      .then((data) => insightsFor.current === id && setInsights({ loading: false, error: null, data }))
      .catch((error) => insightsFor.current === id && setInsights({ loading: false, error, data: null }));
  }, []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const [lastFile, setLastFile] = useState<File | null>(null);
  const loadStatus = useCallback(() => {
    setError(null);
    api.status().then(setStatus).catch(setError);
  }, []);
  useEffect(loadStatus, [loadStatus]);

  const open = useCallback(async (load: () => Promise<DatasetSummary>, label: string) => {
    setBusy(label);
    setError(null);
    try {
      const ds = await load();
      const [p, s] = await Promise.all([api.profile(ds.id), api.suggestions(ds.id)]);
      setDataset(ds);
      setProfile(p);
      setSuggestions(s.suggestions);
      loadInsights(ds.id);
      setAnalyses([]);
      setBuilderResult(null);
      setView("overview");
      window.scrollTo(0, 0);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }, [loadInsights]);

  const handleAnalysis = useCallback(async (run: () => Promise<AnalysisResult>, label: string) => {
    setBusy(label);
    setError(null);
    try {
      const r = await run();
      setAnalyses((a) => [r, ...a]);
      return r;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setBusy(null);
    }
  }, []);

  if (!dataset || !profile) {
    return (
      <UploadScreen
        status={status}
        busy={busy}
        error={error}
        onUpload={(f) => {
          setLastFile(f);
          open(() => api.upload(f), `Reading ${f.name}`);
        }}
        onSample={() => {
          setLastFile(null);
          open(api.sample, "Loading sample data");
        }}
        onRetry={loadStatus}
      />
    );
  }

  const ask = (q: string) => handleAnalysis(() => api.ask(dataset.id, q), "Interpreting your question and calculating");
  const suggestion = (s: Suggestion) => {
    setView("ask");
    if (status?.ai.configured) return ask(s.question);
    return handleAnalysis(() => api.run(dataset.id, s.operation, s.question), "Calculating");
  };
  const investigate = (id: string) => {
    setInvestigateId(id);
    setView("investigate");
    setError(null);
  };
  const openInsightAnalysis = (op: Record<string, unknown>, title: string) => {
    setView("ask");
    window.scrollTo(0, 0);
    handleAnalysis(() => api.run(dataset.id, op, title), "Calculating");
  };
  const runManual = async (op: Record<string, unknown>, label: string) => {
    const r = await handleAnalysis(() => api.run(dataset.id, op, label), "Calculating");
    setBuilderResult(r);
  };

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="sticky top-0 z-20 flex flex-col bg-sidebar text-ink border-r border-line lg:fixed lg:inset-y-0 lg:left-0 lg:w-60">
        <div className="flex items-center gap-2.5 px-5 py-4 lg:py-5">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="font-semibold tracking-tight">DataLens AI</span>
        </div>
        <div className="relative">
        <nav ref={navRef} className="flex gap-1 overflow-x-auto px-3 pb-3 [scrollbar-width:none] lg:flex-col lg:overflow-visible lg:pb-0" aria-label="Main">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => {
                setView(id);
                setError(null);
                window.scrollTo(0, 0);
              }}
              aria-current={view === id || (id === "insights" && view === "investigate") ? "page" : undefined}
              className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm ${view === id || (id === "insights" && view === "investigate") ? "bg-lens-soft font-medium text-lens-deep" : "text-ink-muted hover:bg-surface-2 hover:text-ink"}`}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
              {id === "ask" && analyses.length > 0 && <span className="ml-auto rounded-full bg-lens-soft px-1.5 text-[11px] text-lens-deep">{analyses.length}</span>}
              {id === "insights" && insights.data && insights.data.insights.length > 0 && (
                <span className="ml-auto rounded-full bg-lens-soft px-1.5 text-[11px] text-lens-deep">{insights.data.insights.length}</span>
              )}
            </button>
          ))}
        </nav>
        {/* Hint that the mobile nav scrolls sideways */}
        <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-sidebar to-transparent lg:hidden" aria-hidden="true" />
        </div>
        <div className="mt-auto hidden space-y-3 border-t border-line px-5 py-4 text-xs text-ink-muted lg:block">
          <ThemeToggle />
          <p className="truncate text-ink" title={dataset.name}>{dataset.name}</p>
          <p>{dataset.rows.toLocaleString()} rows · {dataset.columns.length} columns</p>
          <p className="flex items-center gap-1.5" title={status?.ai.configured ? `${status.ai.provider} · ${status.ai.model}` : undefined}>
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${status?.ai.configured ? "bg-lens" : "bg-ink-muted/50"}`} />
            <span className="truncate">{status?.ai.configured ? `AI: ${status.ai.provider}` : "AI not configured"}</span>
          </p>
          {status?.ai.configured && <p className="truncate pl-3 font-mono text-[11px] text-ink-muted">{status.ai.model}</p>}
          {browserEngine.active() && (browserEngine.hasKey()
            ? <button className="pl-3 text-[11px] text-ink-muted underline hover:text-ink" onClick={() => browserEngine.setKey(null)}>Remove my Gemini key</button>
            : <button className="pl-3 text-[11px] font-medium text-lens-deep underline" onClick={browserEngine.promptForKey}>Add my Gemini key</button>)}
          {browserEngine.active() && <p className="text-[11px] leading-snug text-ink-muted">Running entirely in your browser. Your data never leaves this device.</p>}
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 sm:px-8">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{TITLES[view]}</h1>
            <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
              <span>
                {dataset.name}
                {dataset.source === "sample" && " (sample data)"}
              </span>
              {lastFile && dataset.file.sheets.length > 1 && (
                <label className="inline-flex items-center gap-1.5">
                  <span>· Sheet</span>
                  <select
                    className="rounded-md border border-line bg-surface px-2 py-0.5 text-sm text-ink"
                    value={dataset.file.sheet ?? ""}
                    disabled={!!busy}
                    onChange={(e) => {
                      const sheet = e.target.value;
                      open(() => api.upload(lastFile, sheet), `Loading sheet ${sheet}`);
                    }}
                  >
                    {dataset.file.sheets.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>
              )}
              {busy && view !== "ask" && view !== "builder" && <Spinner label={busy} />}
            </div>
          </div>
          <div className="flex gap-2">
            <a className="btn-quiet" href={api.reportUrl(dataset.id)} download
              onClick={(e) => { if (browserEngine.active()) { e.preventDefault(); api.downloadReport(dataset.id).catch(setError); } }}>
              <Download className="h-4 w-4" aria-hidden /> Download report
            </a>
            <button
              className="btn-quiet"
              onClick={() => {
                setDataset(null);
                setProfile(null);
                setError(null);
              }}
            >
              <FileUp className="h-4 w-4" aria-hidden /> New dataset
            </button>
          </div>
        </header>

        {(view === "overview" || view === "health" || view === "data") && error ? (
          <div className="mb-5">
            <ErrorNote error={error} onDismiss={() => setError(null)} />
          </div>
        ) : null}
        {view === "overview" && <div className="mb-6"><LiveDashboard datasetId={dataset.id} profile={profile} /></div>}
        {view === "benchmark" && <BenchmarkView aiConfigured={!!status?.ai.configured} />}
        {view === "overview" && (
          <Overview
            dataset={dataset}
            profile={profile}
            suggestions={suggestions}
            onAsk={suggestion}
            goTo={setView}
            insightsSlot={
              <>
                <WorkflowGuide
                  findings={insights.data?.insights.length ?? null}
                  asked={analyses.length}
                  onGo={(v) => (v === "investigate" && insights.data?.insights[0] ? investigate(insights.data.insights[0].id) : setView(v))}
                />
                <TopInsights data={insights.data} loading={insights.loading} onSeeAll={() => setView("insights")} onInvestigate={investigate} />
              </>
            }
          />
        )}
        {view === "insights" && (
          <InsightsView
            datasetId={dataset.id}
            state={insights}
            aiConfigured={!!status?.ai.configured}
            onRetry={() => loadInsights(dataset.id)}
            onOpenAnalysis={openInsightAnalysis}
            onInvestigate={investigate}
          />
        )}
        {view === "investigate" && investigateId && (
          <InvestigationView datasetId={dataset.id} insightId={investigateId} profile={profile} onBack={() => setView("insights")} onAskOwn={() => setView("ask")} />
        )}
        {view === "whatif" && <WhatIfView datasetId={dataset.id} profile={profile} />}
        {view === "health" && <HealthView datasetId={dataset.id} profile={profile} />}
        {view === "ask" && (
          <AskView
            status={status}
            suggestions={suggestions}
            analyses={analyses}
            busy={busy}
            error={error}
            onAsk={ask}
            onSuggestion={suggestion}
            onDismissError={() => setError(null)}
            goToBuilder={() => setView("builder")}
          />
        )}
        {view === "builder" && (
          <div className="space-y-5">
            <BuilderView dataset={dataset} profile={profile} busy={!!busy} onRun={runManual} />
            <ErrorNote error={error} onDismiss={() => setError(null)} />
            {busy && <Spinner label={busy} />}
            {builderResult && <AnswerCard key={analyses.length} r={builderResult} />}
          </div>
        )}
        {view === "data" && <RecordExplorer datasetId={dataset.id} profile={profile} />}
      </main>
    </div>
  );
}

function WorkflowGuide({ findings, asked, onGo }: { findings: number | null; asked: number; onGo: (v: View) => void }) {
  const steps: { label: string; detail: string; view: View | null; done: boolean; icon: typeof Search }[] = [
    { label: "Upload", detail: "Profiled and checked", view: null, done: true, icon: FileUp },
    { label: "Discover", detail: findings === null ? "Analysing…" : `${findings} finding${findings === 1 ? "" : "s"}`, view: "insights", done: (findings ?? 0) > 0, icon: Lightbulb },
    { label: "Investigate", detail: "Verify a finding", view: "investigate", done: false, icon: Search },
    { label: "Ask", detail: asked ? `${asked} answered` : "Plain-English questions", view: "ask", done: asked > 0, icon: MessageSquareText },
    { label: "Simulate", detail: "What-if scenarios", view: "whatif", done: false, icon: FlaskConical },
  ];
  return (
    <nav aria-label="Workflow" className="panel p-2">
      <ol className="grid gap-1 sm:grid-cols-5">
        {steps.map((s, k) => (
          <li key={s.label} className="flex items-center">
            <button disabled={!s.view || (s.view === "investigate" && !findings)} onClick={() => s.view && onGo(s.view)}
              className="group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left enabled:hover:bg-surface-2 disabled:cursor-default">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-1 ${s.done ? "bg-lens text-on-accent ring-lens" : "bg-surface-2 text-ink-muted ring-line group-enabled:group-hover:text-lens"}`}>
                {s.done ? <Check className="h-4 w-4" aria-hidden /> : <s.icon className="h-4 w-4" aria-hidden />}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{k + 1}. {s.label}</span>
                <span className="block truncate text-xs text-ink-muted">{s.detail}</span>
              </span>
            </button>
            {k < steps.length - 1 && <ChevronRight className="hidden h-4 w-4 shrink-0 text-ink-muted/50 sm:block" aria-hidden />}
          </li>
        ))}
      </ol>
    </nav>
  );
}
