import { ArrowLeft, CheckCircle2, ChevronRight, MessageSquareText, RefreshCw, Scale, Search, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { AnalysisResult, Investigation, Profile, SegmentComparison } from "../types";
import { AnswerCard } from "./AnswerCard";
import { KindTag, LevelBadge } from "./InsightsView";
import { describeFilter, RecordExplorer } from "./RecordExplorer";
import { ResultChart } from "./ResultChart";
import { ErrorNote, Spinner } from "./ui";

interface Props {
  datasetId: string;
  insightId: string;
  profile: Profile;
  onBack: () => void;
  onAskOwn: () => void;
}

function Step({ n, title, icon: Icon, children, subtitle }: { n: number; title: string; icon: typeof Search; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="panel p-5" aria-labelledby={`step-${n}`}>
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-lens-soft text-xs font-semibold text-lens-deep ring-1 ring-lens/30">{n}</span>
        <div>
          <h2 id={`step-${n}`} className="flex items-center gap-2 text-[15px] font-semibold"><Icon className="h-4 w-4 text-lens" aria-hidden /> {title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

export function InvestigationView({ datasetId, insightId, profile, onBack, onAskOwn }: Props) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [seg, setSeg] = useState<SegmentComparison | null>(null);
  const [segError, setSegError] = useState<unknown>(null);
  const [verify, setVerify] = useState<{ state: "idle" | "running" | "match" | "differs" | "error"; result?: AnalysisResult; error?: unknown }>({ state: "idle" });
  const [answers, setAnswers] = useState<AnalysisResult[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [fuError, setFuError] = useState<unknown>(null);

  useEffect(() => {
    setInv(null); setSeg(null); setAnswers([]); setVerify({ state: "idle" });
    api.investigation(datasetId, insightId).then((d) => {
      setInv(d);
      if (d.focus.investigable)
        api.segment(datasetId, { filters: d.focus.filters, baseline_filters: d.focus.baseline_filters, metric: d.focus.metric }).then(setSeg).catch(setSegError);
    }).catch(setError);
    window.scrollTo(0, 0);
  }, [datasetId, insightId]);

  if (error) return <div className="space-y-3"><BackLink onBack={onBack} /><ErrorNote error={error} /></div>;
  if (!inv) return <div className="panel p-5"><Spinner label="Opening the investigation" /></div>;
  const i = inv.insight;

  async function recompute() {
    if (!i.operation) return;
    setVerify({ state: "running" });
    try {
      const r = await api.run(datasetId, i.operation, `Verify: ${i.title}`);
      const same = i.kind === "anomaly" || (i.kind === "data_quality" && i.operation.type === "top_rows")
        ? (r.result?.rows.length ?? -1) === (i.anomalies?.length ?? i.evidence.total_matching)
        : JSON.stringify(r.chart.data ?? []) === JSON.stringify(i.chart.data ?? []);
      setVerify({ state: same ? "match" : "differs", result: r });
    } catch (e) {
      setVerify({ state: "error", error: e });
    }
  }

  async function runFollowUp(q: { question: string; operation: Record<string, unknown> }) {
    setRunning(q.question); setFuError(null);
    try {
      const r = await api.run(datasetId, q.operation, q.question);
      setAnswers((a) => [r, ...a.filter((x) => x.question !== q.question)]);
    } catch (e) {
      setFuError(e);
    } finally {
      setRunning(null);
    }
  }

  const m = seg?.metric;
  return (
    <div className="space-y-5">
      <BackLink onBack={onBack} />
      <header className="panel p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-ink px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-canvas">Investigation</span>
          <KindTag insight={i} />
          <LevelBadge level={i.level} />
        </div>
        <h1 className="text-xl font-semibold leading-snug">{i.title}</h1>
        <p className="mt-1.5 max-w-[80ch] text-[15px] leading-relaxed text-ink-soft">{i.finding}</p>
        {inv.focus.investigable && (
          <p className="mt-3 text-sm text-ink-muted">
            Looking at <strong className="text-ink">{inv.focus.label}</strong>
            {" · "}{inv.focus.filters.map(describeFilter).join(" and ")}
          </p>
        )}
      </header>

      <Step n={1} title="Verify the finding" icon={ShieldCheck} subtitle="Don't take it on trust: rerun the calculation on the data and check every number.">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="min-w-0 space-y-3">
            <p className="text-sm text-ink-soft"><span className="font-medium text-ink">Method.</span> {i.method}</p>
            <ol className="space-y-1.5 text-sm text-ink-soft">
              {i.steps.slice(0, 6).map((s, k) => (
                <li key={k} className="flex gap-2"><span className="mt-0.5 text-xs font-semibold text-lens-deep">{k + 1}.</span><span>{s}</span></li>
              ))}
            </ol>
            {i.operation ? (
              <div className="flex flex-wrap items-center gap-3 pt-1">
                <button className="btn-primary" onClick={recompute} disabled={verify.state === "running"}>
                  <RefreshCw className={`h-4 w-4 ${verify.state === "running" ? "animate-spin" : ""}`} aria-hidden /> Recompute from the data
                </button>
                {verify.state === "match" && <span className="inline-flex items-center gap-1.5 text-sm font-medium text-lens-deep" role="status"><CheckCircle2 className="h-4 w-4" aria-hidden /> Recomputed just now. The result matches the finding exactly.</span>}
                {verify.state === "differs" && <span className="inline-flex items-center gap-1.5 text-sm font-medium text-caution" role="status"><XCircle className="h-4 w-4" aria-hidden /> The recomputed result differs. Compare the chart and table below.</span>}
              </div>
            ) : (
              <p className="text-sm text-ink-muted">This finding is computed directly (not through an analysis operation); its records are in step 3.</p>
            )}
            {verify.state === "error" && <ErrorNote error={verify.error} />}
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
        {verify.result && <div className="mt-4"><AnswerCard r={verify.result} /></div>}
        {!verify.result && i.chart.type !== "none" && <div className="mt-4"><ResultChart chart={i.chart} height={240} /></div>}
      </Step>

      {inv.focus.investigable && (
        <Step n={2} title={`How ${inv.focus.label} differs from ${inv.focus.baseline_label}`} icon={Scale} subtitle={seg?.note}>
          {segError ? <ErrorNote error={segError} /> : !seg ? <Spinner label="Comparing" /> : (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label="Rows" a={seg.segment_rows} b={seg.rest_rows} />
                {m && <Metric label={`Average ${m.column}`} a={m.segment.mean} b={m.rest.mean} />}
                {m && <Metric label={`Median ${m.column}`} a={m.segment.median} b={m.rest.median} />}
                {m && <Metric label={`Total ${m.column}`} a={m.segment.sum} b={m.rest.sum} />}
              </div>
              {seg.category_differences.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">What's over- or under-represented in this segment</h3>
                  <ul className="space-y-2.5">
                    {seg.category_differences.map((d) => (
                      <li key={d.column + d.value} className="grid items-center gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(0,14rem)_1fr_6rem]">
                        <span className="truncate"><span className="text-ink-muted">{d.column}:</span> <span className="font-medium">{d.value}</span></span>
                        <div className="space-y-1" role="img" aria-label={`${d.segment_share}% in segment versus ${d.rest_share}% in comparison`}>
                          <div className="flex items-center gap-2"><span className="h-2 rounded-full bg-lens" style={{ width: `${Math.max(d.segment_share, 1)}%` }} /><span className="text-xs tabular-nums text-ink-muted">{d.segment_share}%</span></div>
                          <div className="flex items-center gap-2"><span className="h-2 rounded-full bg-ink-muted/40" style={{ width: `${Math.max(d.rest_share, 1)}%` }} /><span className="text-xs tabular-nums text-ink-muted">{d.rest_share}%</span></div>
                        </div>
                        <span className={`text-right font-medium tabular-nums ${d.diff_pts > 0 ? "text-lens-deep" : "text-caution"}`}>{d.diff_pts > 0 ? "+" : ""}{d.diff_pts} pts</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 flex items-center gap-4 text-xs text-ink-muted">
                    <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-full bg-lens" /> {inv.focus.label}</span>
                    <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-full bg-ink-muted/40" /> {inv.focus.baseline_label}</span>
                  </p>
                </div>
              )}
              {seg.numeric_differences.length > 0 && (
                <div className="overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label="Numeric differences">
                  <table className="min-w-full text-sm">
                    <thead className="bg-surface-2 text-left text-ink-muted">
                      <tr><th className="px-3 py-2 font-medium">Column</th><th className="px-3 py-2 text-right font-medium">Segment avg</th><th className="px-3 py-2 text-right font-medium">Comparison avg</th><th className="px-3 py-2 text-right font-medium">Standardized diff</th></tr>
                    </thead>
                    <tbody>
                      {seg.numeric_differences.map((d) => (
                        <tr key={d.column} className="border-t border-line">
                          <td className="px-3 py-2 font-medium">{d.column}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmt(d.segment_mean)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-muted">{fmt(d.rest_mean)}</td>
                          <td className={`px-3 py-2 text-right font-medium tabular-nums ${Math.abs(d.std_diff) >= 0.5 ? "text-ink" : "text-ink-muted"}`}>{d.std_diff > 0 ? "+" : ""}{d.std_diff}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Step>
      )}

      {inv.focus.investigable ? (
        <div>
          <p className="mb-2 flex items-center gap-2 px-1 text-sm font-semibold"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-lens-soft text-xs text-lens-deep ring-1 ring-lens/30">3</span> Explore the records behind it</p>
          <RecordExplorer datasetId={datasetId} profile={profile} initialFilters={inv.focus.filters} drillColumns={inv.focus.drill_columns} focusMetric={inv.focus.metric} title={`Records: ${inv.focus.label}`} />
        </div>
      ) : (
        <Step n={3} title="The records behind it" icon={Search} subtitle={i.evidence.note}>
          <p className="text-sm text-ink-muted">{i.evidence.total_matching.toLocaleString()} records. Open the Insights card's Records tab, or the Data table, to browse them.</p>
        </Step>
      )}

      <Step n={inv.focus.investigable ? 4 : 3} title="Follow-up questions" icon={MessageSquareText} subtitle="Built from this finding and your real columns. Each runs through the same validated engine; no AI involved.">
        {inv.follow_ups.length === 0 ? <p className="text-sm text-ink-muted">No follow-ups apply to this finding.</p> : (
          <div className="flex flex-wrap gap-2">
            {inv.follow_ups.map((q) => (
              <button key={q.question} onClick={() => runFollowUp(q)} disabled={!!running}
                className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-left text-[13px] text-ink-soft ring-1 ring-line hover:text-ink hover:ring-lens/40 disabled:opacity-50">
                {running === q.question ? <Spinner /> : <ChevronRight className="h-3.5 w-3.5 text-lens" aria-hidden />} {q.question}
              </button>
            ))}
            <button onClick={onAskOwn} className="rounded-full px-3 py-1.5 text-[13px] font-medium text-lens-deep hover:underline">Ask your own question →</button>
          </div>
        )}
        {fuError ? <div className="mt-3"><ErrorNote error={fuError} onDismiss={() => setFuError(null)} /></div> : null}
        {answers.length > 0 && <div className="mt-4 space-y-4">{answers.map((a) => <AnswerCard key={a.question} r={a} />)}</div>}
      </Step>
    </div>
  );
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink">
      <ArrowLeft className="h-4 w-4" aria-hidden /> All insights
    </button>
  );
}

function Metric({ label, a, b }: { label: string; a: number | null | undefined; b: number | null | undefined }) {
  return (
    <div className="rounded-lg bg-surface-2 p-3.5">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{fmt(a ?? null)}</p>
      <p className="text-xs text-ink-muted">vs <span className="tabular-nums text-ink-soft">{fmt(b ?? null)}</span></p>
    </div>
  );
}
