import { CheckCircle2, ChevronDown, ChevronRight, CircleSlash, Play, RotateCw, XCircle } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { BenchmarkCase, BenchmarkRun, TrackResult } from "../types";
import { ErrorNote, Spinner } from "./ui";

const STATUS: Record<string, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  pass: { label: "Pass", cls: "text-lens-deep bg-lens-soft", Icon: CheckCircle2 },
  fail: { label: "Fail", cls: "text-danger bg-danger-soft", Icon: XCircle },
  error: { label: "Error", cls: "text-caution bg-caution-soft", Icon: XCircle },
  skipped: { label: "Skipped", cls: "text-ink-muted bg-surface-2", Icon: CircleSlash },
  "n/a": { label: "n/a", cls: "text-ink-muted bg-surface-2", Icon: CircleSlash },
};

function Chip({ t }: { t?: TrackResult }) {
  if (!t) return <span className="text-xs text-ink-muted">—</span>;
  const s = STATUS[t.status];
  return <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${s.cls}`}><s.Icon className="h-3 w-3" aria-hidden />{s.label}</span>;
}

const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "number" ? fmt(v) : typeof v === "object" ? JSON.stringify(v) : String(v));

export function BenchmarkView({ aiConfigured }: { aiConfigured: boolean }) {
  const [run, setRun] = useState<BenchmarkRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [includeAi, setIncludeAi] = useState(false);
  const [filter, setFilter] = useState<"all" | "fail">("all");
  const [open, setOpen] = useState<string | null>(null);

  const runAll = async () => {
    setBusy("all"); setError(null);
    try { setRun(await api.runBenchmark({ include_ai: includeAi })); } catch (e) { setError(e); } finally { setBusy(null); }
  };
  const rerun = async (id: string) => {
    if (!run) return;
    setBusy(id);
    try {
      const r = await api.runBenchmark({ ids: [id], include_ai: includeAi });
      setRun({ ...run, results: run.results.map((c) => (c.id === id ? r.results[0] : c)) });
    } catch (e) { setError(e); } finally { setBusy(null); }
  };
  useEffect(() => { api.benchmark().then((b) => (b.last_run ? setRun(b.last_run) : runAll())).catch(setError); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = (run?.results ?? []).filter((c) => filter === "all" || [c.calculation, c.interpretation, c.visualization].some((t) => t && (t.status === "fail" || t.status === "error")));
  const t = run?.tracks;
  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[70ch]">
            <p className="text-lg font-semibold">Accuracy benchmark</p>
            <p className="mt-1 text-sm text-ink-soft">
              {run ? `${run.results.length} questions` : "Questions"} with expected answers computed independently (plain pandas on the raw files; the edge-case set was also verified by hand),
              run through the same pipeline users use. Every score below comes from an actual run{run ? `, at ${new Date(run.ran_at).toLocaleString()}` : ""}.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className={`inline-flex items-center gap-2 text-sm ${aiConfigured ? "" : "opacity-50"}`}>
              <input type="checkbox" className="accent-[rgb(var(--lens))]" disabled={!aiConfigured} checked={includeAi} onChange={(e) => setIncludeAi(e.target.checked)} />
              Include AI interpretation
            </label>
            <button className="btn-primary" onClick={runAll} disabled={!!busy}>{busy === "all" ? <Spinner /> : <Play className="h-4 w-4" aria-hidden />} Run full suite</button>
          </div>
        </div>
        {!aiConfigured && <p className="mt-2 text-xs text-ink-muted">The AI interpretation track needs an API key; without one it's reported as skipped, never scored.</p>}
      </section>
      <ErrorNote error={error} />
      {!run && !error && <div className="panel p-5"><Spinner label="Running the benchmark" /></div>}
      {t && run && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Track title="Calculation correctness" sub="Deterministic · stored operation vs expected answer" s={t.calculation} />
            <Track title="Visualization consistency" sub="Deterministic · chart shows the result's numbers" s={t.visualization} />
            <Track title="AI interpretation" sub="Question text → AI-chosen operation → expected answer" s={t.interpretation} />
            <div className="panel p-4">
              <p className="text-sm font-semibold">Explanation quality</p>
              <p className="mt-0.5 text-xs text-ink-muted">Subjective</p>
              <p className="mt-4 text-sm text-ink-soft">{run.explanation_quality}</p>
            </div>
          </div>
          <section className="panel overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
              <div className="flex gap-1" role="tablist" aria-label="Filter cases">
                {(["all", "fail"] as const).map((f) => (
                  <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)} className={`rounded-md px-2.5 py-1 text-xs font-medium ${filter === f ? "bg-ink text-canvas" : "text-ink-muted hover:text-ink"}`}>
                    {f === "all" ? `All (${run.results.length})` : "Failed or errors"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-ink-muted">Suite v{run.version} · {Object.entries(run.datasets).map(([k, d]) => `${k} ${d.sha256.slice(0, 8)}${d.ok ? "" : " (mismatch)"}`).join(" · ")} · {run.elapsed_ms} ms</p>
            </div>
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Benchmark cases">
              <table className="min-w-full text-sm">
                <thead className="bg-surface-2 text-left text-ink-muted">
                  <tr><th className="px-4 py-2 font-medium">Case</th><th className="px-3 py-2 font-medium">Question</th><th className="px-3 py-2 text-right font-medium">Expected</th><th className="px-3 py-2 text-right font-medium">Actual</th><th className="px-3 py-2 font-medium">Calc</th><th className="px-3 py-2 font-medium">Chart</th><th className="px-3 py-2 font-medium">AI</th><th className="px-3 py-2 text-right font-medium">ms</th><th className="px-3 py-2"><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody>
                  {rows.length === 0 && <tr><td colSpan={9} className="px-4 py-8 text-center text-ink-muted">No failures or errors in this run.</td></tr>}
                  {rows.map((c) => <CaseRow key={c.id} c={c} open={open === c.id} onToggle={() => setOpen(open === c.id ? null : c.id)} onRerun={() => rerun(c.id)} busy={busy === c.id} />)}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Track({ title, sub, s }: { title: string; sub: string; s: BenchmarkRun["tracks"]["calculation"] }) {
  return (
    <div className="panel p-4">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{sub}</p>
      <p className="brand-text mt-3 text-4xl font-bold tabular-nums">{s.accuracy === null ? "—" : `${s.accuracy}%`}</p>
      <p className="mt-1 text-xs text-ink-muted">
        {s.pass} passed · {s.fail} failed · {s.error} errors{s.skipped ? ` · ${s.skipped} skipped` : ""}{s.avg_ms !== null ? ` · avg ${s.avg_ms} ms` : ""}
      </p>
    </div>
  );
}

function CaseRow({ c, open, onToggle, onRerun, busy }: { c: BenchmarkCase; open: boolean; onToggle: () => void; onRerun: () => void; busy: boolean }) {
  const calc = c.calculation;
  return (
    <Fragment>
      <tr className="border-t border-line align-top">
        <td className="whitespace-nowrap px-4 py-2">
          <button className="inline-flex items-center gap-1 font-medium" onClick={onToggle} aria-expanded={open}>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}{c.id}</button>
          <span className="block text-xs text-ink-muted">{c.category}</span>
        </td>
        <td className="min-w-[16rem] px-3 py-2 text-ink-soft">{c.question}</td>
        <td className="max-w-[12rem] truncate px-3 py-2 text-right tabular-nums" title={show(c.expected)}>{c.expected_kind === "table" ? "table" : show(c.expected)}</td>
        <td className="max-w-[12rem] truncate px-3 py-2 text-right tabular-nums" title={show(calc?.actual)}>{c.expected_kind === "table" ? "table" : show(calc?.actual)}</td>
        <td className="px-3 py-2"><Chip t={calc} /></td>
        <td className="px-3 py-2"><Chip t={c.visualization} /></td>
        <td className="px-3 py-2"><Chip t={c.interpretation} /></td>
        <td className="px-3 py-2 text-right tabular-nums text-ink-muted">{calc?.ms ?? "—"}</td>
        <td className="px-3 py-2"><button className="btn-quiet px-2 py-1 text-xs" onClick={onRerun} disabled={busy} aria-label={`Rerun ${c.id}`}>{busy ? <Spinner /> : <RotateCw className="h-3.5 w-3.5" aria-hidden />}</button></td>
      </tr>
      {open && (
        <tr className="bg-surface-2">
          <td colSpan={9} className="px-4 py-3 text-sm">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="font-medium">Calculation</p>
                <p className="text-ink-soft">{calc?.explanation}</p>
                {calc?.difference !== undefined && calc?.difference !== null && <p className="text-xs text-ink-muted">Difference: {String(calc.difference)}</p>}
                {c.expected_kind === "table" && <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">expected {show(c.expected)}<br />actual {show(calc?.actual)}</p>}
                {calc?.operation && <pre className="mt-2 max-h-40 overflow-auto rounded bg-code p-2 font-mono text-[11px] text-code-fg">{JSON.stringify(calc.operation, null, 2)}</pre>}
              </div>
              {c.interpretation && <div><p className="font-medium">AI interpretation</p><p className="text-ink-soft">{c.interpretation.explanation}</p>{c.interpretation.intent && <p className="text-xs text-ink-muted">Interpreted as: {c.interpretation.intent}</p>}</div>}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}
