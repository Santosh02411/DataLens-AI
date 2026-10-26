import {
  Activity, AlertTriangle, ArrowRight, BarChart3, ChevronDown, ChevronRight, Database, GitCompare, Link2, Play, Search, Sparkles, Table2, TrendingUp,
} from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { Insight, InsightKind, InsightLevel, InsightsResponse } from "../types";
import { DataTable } from "./DataTable";
import { ResultChart } from "./ResultChart";
import { ErrorNote, Spinner } from "./ui";

const KIND_ICON: Record<InsightKind, typeof Activity> = {
  group_change: GitCompare,
  trend: TrendingUp,
  period_anomaly: Activity,
  group_difference: BarChart3,
  anomaly: AlertTriangle,
  relationship: Link2,
  missing_pattern: Database,
  data_quality: Database,
};

const LEVEL: Record<InsightLevel, { label: string; cls: string; hint: string }> = {
  strong: { label: "Strong evidence", cls: "bg-lens text-on-accent", hint: "Passed a significance test (adjusted p < 0.001) with a meaningful effect size." },
  moderate: { label: "Moderate evidence", cls: "bg-lens-soft text-lens-deep ring-1 ring-lens/30", hint: "Passed a significance test after adjusting for the number of comparisons." },
  notable: { label: "Worth a look", cls: "bg-caution-soft text-caution ring-1 ring-caution/30", hint: "Flagged by a stated statistical rule rather than a significance test." },
  data_quality: { label: "Data quality", cls: "bg-canvas text-ink-soft ring-1 ring-line", hint: "A property of the data that affects how other numbers should be read." },
  info: { label: "For information", cls: "bg-canvas text-ink-muted ring-1 ring-line", hint: "Context, not a finding." },
};

const FILTERS: { id: string; label: string; kinds: InsightKind[] }[] = [
  { id: "all", label: "All", kinds: [] },
  { id: "time", label: "Over time", kinds: ["trend", "group_change", "period_anomaly"] },
  { id: "groups", label: "Groups", kinds: ["group_difference"] },
  { id: "unusual", label: "Unusual values", kinds: ["anomaly", "period_anomaly"] },
  { id: "relationships", label: "Relationships", kinds: ["relationship"] },
  { id: "quality", label: "Data quality", kinds: ["data_quality", "missing_pattern"] },
];

interface Props {
  datasetId: string;
  state: { loading: boolean; error: unknown; data: InsightsResponse | null };
  aiConfigured: boolean;
  onRetry: () => void;
  onOpenAnalysis: (operation: Record<string, unknown>, title: string) => void;
  onInvestigate: (insightId: string) => void;
}

export function InsightsView({ datasetId, state, aiConfigured, onRetry, onOpenAnalysis, onInvestigate }: Props) {
  const [filter, setFilter] = useState("all");
  const data = state.data;
  const visible = useMemo(() => {
    const kinds = FILTERS.find((f) => f.id === filter)?.kinds ?? [];
    return (data?.insights ?? []).filter((i) => !kinds.length || kinds.includes(i.kind));
  }, [data, filter]);

  if (state.loading) return <InsightsLoading />;
  if (state.error)
    return (
      <div className="space-y-3">
        <ErrorNote error={state.error} />
        <button className="btn-quiet" onClick={onRetry}>Run discovery again</button>
      </div>
    );
  if (!data) return null;

  const available = FILTERS.filter((f) => f.id === "all" || data.insights.some((i) => f.kinds.includes(i.kind)));

  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[68ch]">
            <p className="text-lg font-semibold">
              {data.insights.length
                ? `${data.insights.length} finding${data.insights.length === 1 ? "" : "s"} from ${data.total_checks.toLocaleString()} checks`
                : data.total_checks === 0
                  ? "Not enough data to look for insights"
                  : `No findings passed the evidence thresholds (${data.total_checks.toLocaleString()} checks run)`}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-ink-soft">
              Every number here is computed from your data with Pandas. A finding is shown only if it passes a significance test (adjusted for
              the number of comparisons tried) or a stated statistical rule. AI is used only if you ask it to reword a finding, and its wording
              is checked so it can't add numbers.
            </p>
          </div>
          <p className="text-xs text-ink-muted">Analysed {data.rows.toLocaleString()} rows in {(data.elapsed_ms / 1000).toFixed(1)}s</p>
        </div>
        {data.insights.length > 0 && available.length > 2 && (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Filter findings">
            {available.map((f) => {
              const count = f.id === "all" ? data.insights.length : data.insights.filter((i) => f.kinds.includes(i.kind)).length;
              return (
                <button
                  key={f.id}
                  role="tab"
                  aria-selected={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={`rounded-full px-3 py-1.5 text-[13px] font-medium ${filter === f.id ? "bg-ink text-canvas" : "bg-surface text-ink-soft ring-1 ring-line hover:text-ink"}`}
                >
                  {f.label} <span className={filter === f.id ? "text-white/70" : "text-ink-muted"}>{count}</span>
                </button>
              );
            })}
          </div>
        )}
        <ChecksDetail data={data} />
      </section>

      {data.insights.length === 0 ? (
        <EmptyInsights data={data} />
      ) : (
        visible.map((i) => (
          <InsightCard key={i.id} insight={i} datasetId={datasetId} aiConfigured={aiConfigured} onOpenAnalysis={onOpenAnalysis} onInvestigate={onInvestigate} />
        ))
      )}
    </div>
  );
}

function ChecksDetail({ data }: { data: InsightsResponse }) {
  const [open, setOpen] = useState(false);
  const extra = [...data.not_applicable, ...data.notes];
  return (
    <div className="mt-4 border-t border-line pt-3">
      <button className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted hover:text-ink" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} What was checked
      </button>
      {open && (
        <div className="mt-2 grid gap-4 text-sm md:grid-cols-2">
          <ul className="space-y-1 text-ink-soft">
            {Object.entries(data.checks).map(([k, v]) => (
              <li key={k} className="flex justify-between gap-4 border-b border-line/60 pb-1">
                <span className="first-letter:uppercase">{k}</span>
                <span className="tabular-nums text-ink">{v.toLocaleString()}</span>
              </li>
            ))}
            <li className="flex justify-between gap-4 pb-1">
              <span>Candidate findings before ranking</span>
              <span className="tabular-nums text-ink">{data.candidates_found}</span>
            </li>
          </ul>
          {extra.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-ink-soft">
              {extra.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function EmptyInsights({ data }: { data: InsightsResponse }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface-2 px-6 py-10">
      <p className="font-medium">Nothing stood out strongly enough to report</p>
      <p className="mt-1 max-w-[65ch] text-sm text-ink-soft">
        That usually means the data is fairly uniform or there isn't enough of it for the tests to be confident. DataLens would rather show
        nothing than a weak or accidental pattern. You can still ask your own questions or build an analysis.
      </p>
      {[...data.not_applicable, ...data.notes].length > 0 && (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-ink-soft">
          {[...data.not_applicable, ...data.notes].map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function InsightsLoading() {
  return (
    <div className="space-y-4" aria-busy="true">
      <div className="panel flex items-center gap-3 p-5">
        <Spinner label="Looking for trends, differences and unusual values" />
      </div>
      {[0, 1].map((k) => (
        <div key={k} className="panel animate-pulse space-y-3 p-5">
          <div className="h-4 w-40 rounded bg-canvas" />
          <div className="h-5 w-2/3 rounded bg-canvas" />
          <div className="h-32 rounded bg-canvas" />
        </div>
      ))}
    </div>
  );
}

export function LevelBadge({ level }: { level: InsightLevel }) {
  const l = LEVEL[level];
  return (
    <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${l.cls}`} title={l.hint}>
      {l.label}
    </span>
  );
}

export function KindTag({ insight }: { insight: Insight }) {
  const Icon = KIND_ICON[insight.kind];
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted">
      <Icon className="h-3.5 w-3.5" aria-hidden /> {insight.kind_label}
    </span>
  );
}

function InsightCard({ insight: i, datasetId, aiConfigured, onOpenAnalysis, onInvestigate }: { insight: Insight; datasetId: string; aiConfigured: boolean; onOpenAnalysis: Props["onOpenAnalysis"]; onInvestigate: Props["onInvestigate"] }) {
  const [panel, setPanel] = useState<"none" | "method" | "records">("none");
  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explainError, setExplainError] = useState<unknown>(null);
  const toggle = (p: typeof panel) => setPanel((cur) => (cur === p ? "none" : p));

  async function explain() {
    setExplaining(true);
    setExplainError(null);
    try {
      setExplanation((await api.explain(datasetId, i.id)).explanation);
    } catch (e) {
      setExplainError(e);
    } finally {
      setExplaining(false);
    }
  }

  return (
    <article className="panel overflow-hidden" aria-labelledby={`ins-${i.id}`}>
      <div className="p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <KindTag insight={i} />
          <LevelBadge level={i.level} />
          {i.nature === "statistical_anomaly" && <span className="text-[11px] text-ink-muted">Statistically unusual, not a confirmed error</span>}
          {i.nature === "data_quality" && <span className="text-[11px] text-ink-muted">Possible data issue, not confirmed</span>}
        </div>
        <h2 id={`ins-${i.id}`} className="text-[17px] font-semibold leading-snug">{i.title}</h2>
        <p className="mt-1.5 max-w-[75ch] text-[15px] leading-relaxed text-ink-soft">{i.finding}</p>

        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <div className="min-w-0">
            {i.chart.type !== "none" ? (
              <ResultChart chart={i.chart} height={240} />
            ) : (
              <DataTable columns={i.evidence.columns} rows={i.evidence.rows.slice(0, 6)} maxHeight="16rem" dense label={`Sample records: ${i.title}`} />
            )}
          </div>
          <dl className="space-y-2 self-start rounded-lg bg-surface-2 p-3.5 text-sm">
            {i.stats.map((s) => (
              <div key={s.label} className="flex items-baseline justify-between gap-3">
                <dt className="text-ink-muted">{s.label}</dt>
                <dd className="shrink-0 whitespace-nowrap text-right font-medium tabular-nums">{fmt(s.value)}</dd>
              </div>
            ))}
          </dl>
        </div>

        {i.anomalies && i.anomalies.length > 0 && (
          <div className="mt-4 overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label={`Flagged records: ${i.title}`}>
            <table className="min-w-full text-sm">
              <thead className="bg-surface-2 text-left text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Record</th>
                  <th className="px-3 py-2 text-right font-medium">Observed</th>
                  <th className="px-3 py-2 text-right font-medium">Median</th>
                  <th className="px-3 py-2 text-right font-medium">Limit</th>
                  <th className="px-3 py-2 font-medium">Why it was flagged</th>
                </tr>
              </thead>
              <tbody>
                {i.anomalies.map((a) => (
                  <tr key={a.record} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-3 py-2 font-medium">{a.record}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(a.observed)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink-muted">{fmt(a.baseline_median)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink-muted">{fmt(a.limit)}</td>
                    <td className="min-w-[16rem] px-3 py-2 text-ink-soft">{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {explanation && (
          <div className="mt-4 rounded-lg border border-dashed border-ai/40 bg-ai-soft px-4 py-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-ai">
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> AI-written explanation
            </p>
            <p className="mt-1 text-[15px] leading-relaxed text-ink">{explanation}</p>
            <p className="mt-1.5 text-xs text-ink-muted">Wording only. Every number in it was checked against the computed statistics above.</p>
          </div>
        )}
        {explainError ? <div className="mt-3"><ErrorNote error={explainError} onDismiss={() => setExplainError(null)} /></div> : null}
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2 px-5 py-3">
        {!i.context?.duplicates && (
          <button className="btn-primary py-1.5 text-xs" onClick={() => onInvestigate(i.id)}>
            <Search className="h-3.5 w-3.5" aria-hidden /> Investigate
          </button>
        )}
        <button className={`btn py-1.5 text-xs ${panel === "method" ? "bg-ink text-canvas" : "btn-quiet"}`} onClick={() => toggle("method")} aria-expanded={panel === "method"}>
          How this was found
        </button>
        <button className={`btn py-1.5 text-xs ${panel === "records" ? "bg-ink text-canvas" : "btn-quiet"}`} onClick={() => toggle("records")} aria-expanded={panel === "records"}>
          <Table2 className="h-3.5 w-3.5" aria-hidden /> Records ({i.evidence.total_matching.toLocaleString()})
        </button>
        {i.operation && (
          <button className="btn-quiet py-1.5 text-xs" onClick={() => onOpenAnalysis(i.operation!, i.title)}>
            <Play className="h-3.5 w-3.5" aria-hidden /> Open as analysis
          </button>
        )}
        <span className="flex-1" />
        {aiConfigured ? (
          !explanation && (
            <button className="btn-quiet py-1.5 text-xs" onClick={explain} disabled={explaining}>
              {explaining ? <Spinner label="Writing" /> : <><Sparkles className="h-3.5 w-3.5 text-ai" aria-hidden /> Explain in plain words</>}
            </button>
          )
        ) : (
          <span className="text-xs text-ink-muted">Add an API key to get optional AI wording</span>
        )}
      </footer>

      {panel === "method" && (
        <div className="border-t border-line bg-surface-2 px-5 py-4 text-sm">
          <p className="font-medium text-lens-deep">Method</p>
          <p className="mt-1 max-w-[80ch] text-ink-soft">{i.method}</p>
          <ol className="mt-3 space-y-2">
            {i.steps.map((s, k) => (
              <li key={k} className="flex gap-3 text-ink-soft">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-lens/40 bg-surface text-[10px] font-semibold text-lens-deep">{k + 1}</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
          {i.caveats.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-line pt-3 text-ink-soft">
              {i.caveats.map((c) => (
                <li key={c} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-caution" aria-hidden />
                  {c}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {panel === "records" && (
        <div className="border-t border-line px-5 py-4">
          <p className="mb-2 text-xs text-ink-muted">
            {i.evidence.note}. Showing {Math.min(i.evidence.rows.length, i.evidence.total_matching)} of {i.evidence.total_matching.toLocaleString()} rows, straight from your data.
            {i.operation ? " Open as analysis to explore them with the full engine." : ""}
          </p>
          <DataTable columns={i.evidence.columns} rows={i.evidence.rows} maxHeight="22rem" dense label={`Records behind: ${i.title}`} />
        </div>
      )}
    </article>
  );
}

export function TopInsights({ data, loading, onSeeAll, onInvestigate }: { data: InsightsResponse | null; loading: boolean; onSeeAll: () => void; onInvestigate: (id: string) => void }) {
  if (loading)
    return (
      <section className="panel p-5">
        <Spinner label="Discovering insights" />
      </section>
    );
  if (!data) return null;
  const top = data.insights.slice(0, 3);
  return (
    <section className="panel p-5">
      <div className="mb-3 flex items-end justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Top findings</h2>
        <button className="inline-flex items-center gap-1 text-xs font-medium text-lens-deep hover:underline" onClick={onSeeAll}>
          {data.insights.length ? `All ${data.insights.length} insights` : "Details"} <ArrowRight className="h-3 w-3" />
        </button>
      </div>
      {top.length === 0 ? (
        <p className="text-sm text-ink-muted">No findings passed the evidence thresholds. See Insights for what was checked.</p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          {top.map((i) => (
            <button key={i.id} onClick={() => (i.context?.duplicates ? onSeeAll() : onInvestigate(i.id))} className="rounded-lg border border-line p-3.5 text-left hover:border-lens/50 hover:bg-lens-soft/30" aria-label={`Investigate: ${i.title}`}>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <KindTag insight={i} />
                <LevelBadge level={i.level} />
              </div>
              <p className="text-sm font-semibold leading-snug">{i.title}</p>
              <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-ink-muted">{i.finding}</p>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
