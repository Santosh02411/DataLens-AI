import { ArrowRight, MessageSquareText } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { bytes, TYPE_LABEL } from "../format";
import type { ReactNode } from "react";
import { useChartColors } from "../ThemeContext";
import { tooltipProps } from "./ResultChart";
import type { DatasetSummary, Profile, Suggestion } from "../types";
import { SectionTitle, SeverityDot } from "./ui";

interface Props {
  dataset: DatasetSummary;
  profile: Profile;
  suggestions: Suggestion[];
  onAsk: (s: Suggestion) => void;
  goTo: (view: "health" | "ask" | "insights") => void;
  insightsSlot?: ReactNode;
}

function scoreTone(score: number) {
  if (score >= 90) return "text-lens";
  if (score >= 70) return "text-caution";
  return "text-danger";
}

export function Overview({ dataset, profile, suggestions, onAsk, goTo, insightsSlot }: Props) {
  const c = useChartColors();
  const missing = profile.column_profiles.filter((c) => c.missing > 0).map((c) => ({ column: c.name, pct: c.missing_pct, missing: c.missing }));
  const typeEntries = Object.entries(profile.type_counts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-6">
      <section className="panel grid grid-cols-2 overflow-hidden md:grid-cols-[1.2fr_repeat(4,1fr)]">
        <div className="col-span-2 p-5 md:col-span-1">
          <p className="text-sm text-ink-muted">Data quality score</p>
          <p className={`mt-1 text-5xl font-semibold tracking-tight tabular-nums ${scoreTone(profile.quality_score)}`}>
            {profile.quality_score}
            <span className="text-xl text-ink-muted">/100</span>
          </p>
          <p className="mt-2 text-xs leading-relaxed text-ink-muted">{profile.quality_formula}.</p>
        </div>
        {[
          ["Rows", profile.rows.toLocaleString(), dataset.file.type === "excel" && dataset.file.sheet ? `Sheet: ${dataset.file.sheet}` : bytes(dataset.file.size_bytes)],
          ["Columns", String(profile.columns), typeEntries.map(([t, n]) => `${n} ${TYPE_LABEL[t]?.toLowerCase() ?? t}`).slice(0, 2).join(", ")],
          ["Missing cells", profile.missing_cells.toLocaleString(), `${profile.missing_pct}% of all cells`],
          ["Duplicate rows", profile.duplicate_rows.toLocaleString(), `${profile.duplicate_pct}% of rows`],
        ].map(([label, value, sub]) => (
          <div key={label} className="border-t border-line p-5 even:border-r md:border-l md:border-t-0 md:even:border-r-0">
            <p className="text-sm text-ink-muted">{label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
            <p className="mt-1 truncate text-xs text-ink-muted">{sub}</p>
          </div>
        ))}
      </section>

      {dataset.notes.length > 0 && (
        <section className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-sm font-medium">How the file was read</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-soft">
            {dataset.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      {insightsSlot}

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <section className="panel p-5">
          <SectionTitle aside={<span className="text-xs text-ink-muted">% of rows missing</span>}>Missing values by column</SectionTitle>
          {missing.length ? (
            <div role="figure" aria-label={`Bar chart of missing values: ${missing.map((m) => `${m.column} ${m.pct}%`).join(", ")}.`}>
            <div aria-hidden="true">
            <ResponsiveContainer width="100%" height={Math.max(160, missing.length * 34 + 30)}>
              <BarChart data={missing} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                <CartesianGrid stroke={c.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12, fill: c.axis }} stroke={c.line} unit="%" domain={[0, (max: number) => Math.max(5, Math.ceil(max))]} />
                <YAxis type="category" dataKey="column" tick={{ fontSize: 12, fill: c.text }} width={120} stroke={c.line} />
                <Tooltip formatter={(v: number, _n, p) => [`${v}% (${p.payload.missing.toLocaleString()} rows)`, "Missing"]} {...tooltipProps(c)} cursor={{ fill: c.cursor }} />
                <Bar dataKey="pct" fill={c.caution} radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
            </div>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-ink-muted">Every column is complete. No missing values.</p>
          )}
        </section>

        <section className="panel p-5">
          <SectionTitle
            aside={
              <button className="inline-flex items-center gap-1 text-xs font-medium text-lens-deep hover:underline" onClick={() => goTo("health")}>
                All checks <ArrowRight className="h-3 w-3" />
              </button>
            }
          >
            What needs attention
          </SectionTitle>
          {profile.issues.length ? (
            <ul className="space-y-3">
              {profile.issues.slice(0, 6).map((i, k) => (
                <li key={k} className="flex gap-2.5">
                  <SeverityDot severity={i.severity} />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{i.title}</p>
                    <p className="text-xs leading-relaxed text-ink-muted">{i.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-8 text-center text-sm text-ink-muted">No data quality issues found.</p>
          )}
        </section>
      </div>

      {suggestions.length > 0 && (
        <section className="panel p-5">
          <SectionTitle
            aside={
              <button className="inline-flex items-center gap-1 text-xs font-medium text-lens-deep hover:underline" onClick={() => goTo("ask")}>
                Ask your own <ArrowRight className="h-3 w-3" />
              </button>
            }
          >
            Questions this data can answer
          </SectionTitle>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {suggestions.map((s) => (
              <button key={s.question} onClick={() => onAsk(s)} className="group flex items-start gap-2.5 rounded-lg border border-line px-3.5 py-3 text-left hover:border-lens/50 hover:bg-lens-soft/40">
                <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-lens" aria-hidden />
                <span>
                  <span className="block text-sm font-medium leading-snug">{s.question}</span>
                  <span className="text-xs text-ink-muted">{s.kind}</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
