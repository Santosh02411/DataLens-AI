import { FlaskConical, Info, Link2, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { FilterSpec, Profile, ScenarioOptions, ScenarioResult } from "../types";
import { DataTable } from "./DataTable";
import { ResultChart } from "./ResultChart";
import { ErrorNote, Spinner, Warnings } from "./ui";

const OPS: [string, string][] = [["eq", "is"], ["ne", "is not"], ["gt", ">"], ["lt", "<"]];

export function WhatIfView({ datasetId, profile }: { datasetId: string; profile: Profile }) {
  const [opts, setOpts] = useState<ScenarioOptions | null>(null);
  const [optsError, setOptsError] = useState<unknown>(null);
  const [target, setTarget] = useState("");
  const [agg, setAgg] = useState("sum");
  const [adj, setAdj] = useState<Record<string, number>>({});
  const [exclude, setExclude] = useState<FilterSpec[]>([]);
  const [groupBy, setGroupBy] = useState("");
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.scenarioOptions(datasetId).then((o) => {
      setOpts(o);
      setTarget(o.targets[0] ?? "");
      setGroupBy(o.group_columns.find((c) => /region|channel|category|segment/i.test(c)) ?? "");
    }).catch(setOptsError);
  }, [datasetId]);

  const linked = useMemo(() => opts?.adjustable.filter((a) => a.affects.includes(target)) ?? [], [opts, target]);
  const unlinked = useMemo(() => opts?.adjustable.filter((a) => !a.affects.includes(target)) ?? [], [opts, target]);
  const formula = opts?.formulas.find((f) => f.target === target);
  const active = Object.entries(adj).filter(([c, v]) => v !== 0 && linked.some((l) => l.column === c));
  const validExclude = exclude.filter((f) => f.column && (f.value !== "" && f.value !== null));
  const ready = !!target && (active.length > 0 || validExclude.length > 0);

  useEffect(() => {
    if (!ready) { setResult(null); setError(null); return; }
    const t = setTimeout(() => {
      setLoading(true);
      api.scenario(datasetId, { target, agg, adjustments: active.map(([column, percent]) => ({ column, percent })), exclude: validExclude, group_by: groupBy || null })
        .then((r) => { setResult(r); setError(null); })
        .catch((e) => { setError(e); setResult(null); })
        .finally(() => setLoading(false));
    }, 350);
    return () => clearTimeout(t);
  }, [datasetId, target, agg, JSON.stringify(active), JSON.stringify(validExclude), groupBy, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  if (optsError) return <ErrorNote error={optsError} />;
  if (!opts) return <div className="panel p-5"><Spinner label="Reading which scenarios this data supports" /></div>;
  if (!opts.available) return (
    <div className="rounded-xl border border-dashed border-line bg-surface-2 px-6 py-10">
      <p className="font-medium">This dataset has no number columns to simulate</p>
      <p className="mt-1 text-sm text-ink-soft">What-if scenarios recalculate numeric measures. Upload data with at least one number column to try it.</p>
    </div>
  );

  const presets: { label: string; apply: () => void }[] = [];
  for (const f of opts.formulas) {
    const priceLike = f.terms.find((t) => /price|rate|fee/i.test(t));
    const costLike = f.terms.find((t) => /cost|expense|spend/i.test(t));
    if (priceLike) presets.push({ label: `Prices +5% → ${f.target}`, apply: () => { setTarget(f.target); setAgg("sum"); setAdj({ [priceLike]: 5 }); setExclude([]); } });
    if (costLike) presets.push({ label: `Costs +10% → ${f.target}`, apply: () => { setTarget(f.target); setAgg("sum"); setAdj({ [costLike]: 10 }); setExclude([]); } });
  }
  const sx = opts.suggested_exclusion;  // computed server-side: the exclusion that moves a measure the most
  if (sx) presets.push({ label: `Average ${sx.target} without ${sx.column} = ${sx.value}`, apply: () => { setTarget(sx.target); setAgg("mean"); setAdj({}); setExclude([{ column: sx.column, op: "eq", value: sx.value }]); } });

  return (
    <div className="space-y-5">
      <section className="flex items-start gap-3 rounded-xl border border-ai/30 bg-ai-soft px-4 py-3 text-sm">
        <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-ai" aria-hidden />
        <p className="text-ink-soft"><strong className="text-ink">Hypothetical scenarios, not observed data.</strong> Each scenario recalculates this dataset with your changes. It doesn't predict the future or model how people would react. A change only affects other columns through relationships found in the data.</p>
      </section>

      <div className="grid gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="panel space-y-5 self-start p-5" aria-label="Scenario controls">
          {presets.length > 0 && (
            <div>
              <p className="label">Try a scenario</p>
              <div className="flex flex-wrap gap-2">
                {presets.slice(0, 3).map((p) => <button key={p.label} onClick={p.apply} className="rounded-full bg-surface-2 px-3 py-1.5 text-left text-[13px] text-ink-soft ring-1 ring-line hover:text-ink hover:ring-lens/40">{p.label}</button>)}
              </div>
            </div>
          )}
          <div className="grid grid-cols-[1fr_7rem] gap-2">
            <label className="block"><span className="label">Measure</span>
              <select className="field" value={target} onChange={(e) => { setTarget(e.target.value); setAdj({}); }}>{opts.targets.map((t) => <option key={t}>{t}</option>)}</select>
            </label>
            <label className="block"><span className="label">As</span>
              <select className="field" value={agg} onChange={(e) => setAgg(e.target.value)}><option value="sum">Total</option><option value="mean">Average</option><option value="median">Median</option></select>
            </label>
          </div>
          {formula && (
            <p className="flex items-start gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs text-ink-soft">
              <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-lens" aria-hidden />
              <span>Detected in the data: <code className="font-mono text-ink">{formula.expression}</code> (holds for {(formula.holds_share * 100).toFixed(1)}% of rows)</span>
            </p>
          )}
          <div>
            <p className="label">Adjust</p>
            <div className="space-y-4">
              {linked.map((a) => {
                const v = adj[a.column] ?? 0;
                return (
                  <div key={a.column}>
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <label htmlFor={`adj-${a.column}`} className="font-medium">{a.column}{a.column === target ? " (directly)" : ""}</label>
                      <span className="flex items-center gap-1">
                        <input type="number" aria-label={`${a.column} change in percent`} className="w-16 rounded-md border border-line bg-surface px-1.5 py-0.5 text-right text-sm tabular-nums" min={-90} max={200} value={v}
                          onChange={(e) => setAdj({ ...adj, [a.column]: Math.max(-90, Math.min(200, Number(e.target.value) || 0)) })} />
                        <span className="text-ink-muted">%</span>
                      </span>
                    </div>
                    <input id={`adj-${a.column}`} type="range" min={-50} max={50} step={1} value={Math.max(-50, Math.min(50, v))} className="w-full accent-[rgb(var(--lens))]"
                      onChange={(e) => setAdj({ ...adj, [a.column]: Number(e.target.value) })} aria-valuetext={`${v} percent`} />
                  </div>
                );
              })}
            </div>
            {unlinked.length > 0 && (
              <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-muted">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>{unlinked.map((u) => u.column).join(", ")} can't change {target}: no relationship was detected, and DataLens won't assume one.</span>
              </p>
            )}
          </div>
          <div>
            <p className="label">Exclude records</p>
            <div className="space-y-2">
              {exclude.map((f, k) => (
                <div key={k} className="grid grid-cols-[1fr_5rem_1fr_auto] gap-1.5">
                  <select className="field px-2" aria-label="Exclude column" value={f.column} onChange={(e) => setExclude(exclude.map((x, j) => (j === k ? { ...x, column: e.target.value } : x)))}>{opts.filter_columns.map((c) => <option key={c}>{c}</option>)}</select>
                  <select className="field px-2" aria-label="Exclude condition" value={f.op} onChange={(e) => setExclude(exclude.map((x, j) => (j === k ? { ...x, op: e.target.value } : x)))}>{OPS.map(([o, l]) => <option key={o} value={o}>{l}</option>)}</select>
                  <input className="field px-2" aria-label="Exclude value" list={`ex-${k}`} value={String(f.value ?? "")} onChange={(e) => setExclude(exclude.map((x, j) => (j === k ? { ...x, value: ["gt", "lt"].includes(x.op) && e.target.value !== "" && !Number.isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value } : x)))} />
                  <datalist id={`ex-${k}`}>{(profile.column_profiles.find((c) => c.name === f.column)?.top_values ?? []).map((t) => <option key={t.value} value={t.value} />)}</datalist>
                  <button className="btn-quiet px-2" onClick={() => setExclude(exclude.filter((_, j) => j !== k))} aria-label="Remove exclusion"><X className="h-4 w-4" /></button>
                </div>
              ))}
              {exclude.length < 3 && (
                <button className="inline-flex items-center gap-1 text-sm font-medium text-lens-deep hover:underline" onClick={() => setExclude([...exclude, { column: opts.group_columns[0] ?? opts.filter_columns[0], op: "eq", value: "" }])}>
                  <Plus className="h-4 w-4" aria-hidden /> Exclude records where…
                </button>
              )}
            </div>
          </div>
          <label className="block"><span className="label">Break down by</span>
            <select className="field" value={groupBy} onChange={(e) => setGroupBy(e.target.value)}><option value="">No breakdown</option>{opts.group_columns.map((c) => <option key={c}>{c}</option>)}</select>
          </label>
          <button className="btn-quiet w-full" onClick={() => { setAdj({}); setExclude([]); }}><RotateCcw className="h-4 w-4" aria-hidden /> Reset scenario</button>
        </section>

        <section className="min-w-0 space-y-4" aria-live="polite" aria-label="Scenario results">
          {!ready && (
            <div className="rounded-xl border border-dashed border-line bg-surface-2 px-6 py-12 text-center">
              <FlaskConical className="mx-auto h-7 w-7 text-ai" aria-hidden />
              <p className="mt-2 font-medium">Move a slider or pick a preset</p>
              <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">Results recalculate on the server from the real data. You'll see the observed value, the hypothetical one, and exactly how it was computed.</p>
            </div>
          )}
          {ready && loading && !result && <div className="panel p-5"><Spinner label="Recalculating" /></div>}
          {error ? <ErrorNote error={error} /> : null}
          {result && (
            <article className="panel overflow-hidden">
              <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
                <span className="rounded-md bg-ai-soft px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-ai ring-1 ring-ai/30">Hypothetical scenario</span>
                {loading && <Spinner />}
              </div>
              <div className="grid gap-px bg-line sm:grid-cols-3">
                <Kpi label={`Observed ${result.label}`} value={fmt(result.baseline)} sub={`${result.rows_baseline.toLocaleString()} rows`} />
                <Kpi label={`Scenario ${result.label}`} value={fmt(result.scenario)} sub={`${result.rows_scenario.toLocaleString()} rows`} accent />
                <Kpi label="Difference" value={`${result.change >= 0 ? "+" : ""}${fmt(result.change)}`} sub={result.pct_change === null ? "" : `${result.pct_change >= 0 ? "+" : ""}${result.pct_change.toFixed(2)}%`} />
              </div>
              <div className="space-y-4 p-5">
                <p className="text-[15px] leading-relaxed">{result.summary}</p>
                <Warnings items={result.warnings} />
                <ResultChart chart={result.chart} height={260} />
                {result.breakdown.length > 0 && result.group_by && (
                  <DataTable columns={[result.group_by, "baseline", "scenario", "change", "% change"]} rows={result.breakdown} maxHeight="18rem" dense label="Scenario breakdown" />
                )}
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h2 className="mb-1.5 text-sm font-semibold text-lens-deep">How it was calculated</h2>
                    <ol className="space-y-1 text-sm text-ink-soft">{result.steps.map((s, k) => <li key={k} className="flex gap-2"><span className="text-xs font-semibold text-lens-deep">{k + 1}.</span>{s}</li>)}</ol>
                  </div>
                  <div>
                    <h2 className="mb-1.5 text-sm font-semibold text-ai">Assumptions</h2>
                    <ul className="list-disc space-y-1 pl-4 text-sm text-ink-soft">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
                  </div>
                </div>
              </div>
            </article>
          )}
        </section>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: boolean }) {
  return (
    <div className="bg-surface px-5 py-4">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accent ? "text-ai" : ""}`}>{value}</p>
      <p className="text-xs text-ink-muted">{sub}</p>
    </div>
  );
}
