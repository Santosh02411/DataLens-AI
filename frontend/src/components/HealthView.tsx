import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { AnalysisResult, ColumnProfile, Profile } from "../types";
import { ResultChart } from "./ResultChart";
import { ErrorNote, SectionTitle, SeverityDot, Spinner, TypeBadge } from "./ui";

export function HealthView({ datasetId, profile }: { datasetId: string; profile: Profile }) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <section className="panel p-5">
        <SectionTitle aside={<span className="text-xs text-ink-muted">{profile.issues.length} found</span>}>Quality checks</SectionTitle>
        {profile.issues.length === 0 ? (
          <p className="text-sm text-ink-muted">No missing values, duplicates, constant columns or unusual values were found.</p>
        ) : (
          <ul className="grid gap-x-8 gap-y-3 md:grid-cols-2">
            {profile.issues.map((i, k) => (
              <li key={k} className="flex gap-2.5">
                <SeverityDot severity={i.severity} />
                <div>
                  <p className="text-sm font-medium">{i.title}</p>
                  <p className="text-xs leading-relaxed text-ink-muted">{i.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 border-t border-line pt-3 text-xs text-ink-muted">
          Completeness {profile.completeness_pct}% · Row uniqueness {profile.uniqueness_pct}% · Unusual values use a robust modified z-score (≥ 3.5), the same rule as Insights.
        </p>
      </section>

      <section className="panel overflow-hidden">
        <div className="px-5 pt-5">
          <SectionTitle aside={<span className="text-xs text-ink-muted">Select a column for details</span>}>Columns</SectionTitle>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-surface-2 text-left text-ink-muted">
              <tr>
                <th className="px-5 py-2 font-medium">Column</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Missing</th>
                <th className="px-3 py-2 text-right font-medium">Distinct</th>
                <th className="px-5 py-2 font-medium">Summary</th>
              </tr>
            </thead>
            <tbody>
              {profile.column_profiles.map((c) => (
                <Fragment key={c.name}>
                  <tr className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(open === c.name ? null : c.name)}>
                    <td className="px-5 py-2.5 font-medium">
                      <button className="inline-flex items-center gap-1.5" aria-expanded={open === c.name}>
                        {open === c.name ? <ChevronDown className="h-3.5 w-3.5 text-ink-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-ink-muted" />}
                        {c.name}
                      </button>
                    </td>
                    <td className="px-3 py-2.5"><TypeBadge type={c.type} /></td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-canvas">
                          <div className={`h-full ${c.missing_pct >= 10 ? "bg-caution" : "bg-lens"}`} style={{ width: `${Math.min(100, c.missing_pct)}%` }} />
                        </div>
                        <span className="tabular-nums text-ink-soft">{c.missing ? `${c.missing_pct}%` : "none"}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{c.unique.toLocaleString()}</td>
                    <td className="max-w-[22rem] truncate px-5 py-2.5 text-ink-soft">{summary(c)}</td>
                  </tr>
                  {open === c.name && (
                    <tr className="bg-surface-2">
                      <td colSpan={5} className="px-5 pb-5 pt-2">
                        <ColumnDetail datasetId={datasetId} col={c} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function summary(c: ColumnProfile): string {
  const s = c.stats;
  if (c.type === "numeric" && s) return `${fmt(s.min as number)} to ${fmt(s.max as number)} · median ${fmt(s.median ?? null)}`;
  if (c.type === "datetime" && s) return `${s.min} to ${s.max}`;
  if (c.top_values?.length) return `Most common: ${c.top_values[0].value} (${c.top_values[0].pct}%)`;
  return c.sample_values.join(", ");
}

function ColumnDetail({ datasetId, col }: { datasetId: string; col: ColumnProfile }) {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const s = col.stats;

  async function loadDistribution() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.run(datasetId, { type: "distribution", column: col.name, bins: 20 }, `How are ${col.name} values distributed?`));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {col.type === "numeric" && s
          ? ([
              ["Mean", s.mean], ["Median", s.median], ["Std dev", s.std], ["Sum", s.sum],
              ["Min", s.min], ["Max", s.max], ["Zeros", s.zeros], ["Negatives", s.negatives], ["Unusual values", s.outliers],
            ] as [string, number | null | undefined][]).map(([k, v]) => (
              <Fragment key={k}>
                <dt className="text-ink-muted">{k}</dt>
                <dd className="text-right font-medium tabular-nums">{fmt(v ?? null)}</dd>
              </Fragment>
            ))
          : null}
        {col.type === "datetime" && s && (
          <>
            <dt className="text-ink-muted">Earliest</dt><dd className="text-right font-medium">{String(s.min)}</dd>
            <dt className="text-ink-muted">Latest</dt><dd className="text-right font-medium">{String(s.max)}</dd>
            <dt className="text-ink-muted">Span</dt><dd className="text-right font-medium">{s.span_days?.toLocaleString()} days</dd>
          </>
        )}
        <dt className="text-ink-muted">Missing</dt>
        <dd className="text-right font-medium tabular-nums">{col.missing.toLocaleString()}</dd>
        <dt className="text-ink-muted">Stored as</dt>
        <dd className="text-right font-mono text-xs">{col.dtype}</dd>
      </dl>

      <div className="min-w-0">
        {col.top_values && col.type !== "identifier" && (
          <ul className="mb-4 space-y-1.5">
            {col.top_values.map((t) => (
              <li key={t.value} className="grid grid-cols-[minmax(0,10rem)_1fr_4rem] items-center gap-3 text-sm">
                <span className="truncate">{t.value}</span>
                <span className="h-2 overflow-hidden rounded-full bg-canvas"><span className="block h-full bg-lens" style={{ width: `${t.pct}%` }} /></span>
                <span className="text-right tabular-nums text-ink-muted">{t.pct}%</span>
              </li>
            ))}
          </ul>
        )}
        {col.type !== "identifier" && col.type !== "text" && !result && (
          <button className="btn-quiet text-xs" onClick={loadDistribution} disabled={loading}>
            {loading ? <Spinner label="Calculating" /> : "Show full distribution"}
          </button>
        )}
        <ErrorNote error={error} />
        {result && (
          <div>
            <p className="mb-2 text-sm text-ink-soft">{result.answer}</p>
            <ResultChart chart={result.chart} height={220} />
          </div>
        )}
      </div>
    </div>
  );
}
