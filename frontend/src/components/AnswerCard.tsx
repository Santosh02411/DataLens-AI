import { Ban, Braces, Download, Sparkles, Table2, Wrench } from "lucide-react";
import { useState } from "react";
import { downloadCsv, fmt } from "../format";
import type { AnalysisResult } from "../types";
import { DataTable } from "./DataTable";
import { ResultChart } from "./ResultChart";
import { Warnings } from "./ui";

type Tab = "result" | "evidence";

export function AnswerCard({ r }: { r: AnalysisResult }) {
  const [tab, setTab] = useState<Tab>("result");
  const [showJson, setShowJson] = useState(false);
  const modeBadge = (
    <span className="inline-flex items-center gap-1 rounded-md bg-canvas px-1.5 py-0.5 text-[11px] font-medium text-ink-muted">
      {r.mode === "ai" ? <Sparkles className="h-3 w-3" aria-hidden /> : <Wrench className="h-3 w-3" aria-hidden />}
      {r.mode === "ai" ? "AI interpreted" : "No AI used"}
    </span>
  );

  if (r.status === "unanswerable") {
    return (
      <article className="panel answer-in border-l-4 border-ink p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-[15px] font-semibold">{r.question}</h2>
          {modeBadge}
        </div>
        <p className="flex items-start gap-2 text-[15px] leading-relaxed text-ink">
          <Ban className="mt-1 h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
          <span>
            <span className="font-semibold">This data can't answer that.</span> {r.answer}
          </span>
        </p>
        {r.missing && r.missing.length > 0 && (
          <p className="mt-3 text-sm text-ink-muted">
            Missing from the dataset: {r.missing.map((m) => <span key={m} className="mr-1.5 rounded-md bg-canvas px-1.5 py-0.5 text-ink">{m}</span>)}
          </p>
        )}
        <p className="mt-3 text-xs text-ink-muted">No numbers were produced, because none could be computed honestly.</p>
      </article>
    );
  }

  const result = r.result;
  const scalar = result?.scalar;
  const stem = r.question.replace(/[^\w]+/g, "-").replace(/^-|-$/g, "").slice(0, 50).toLowerCase() || "result";

  return (
    <article className="panel answer-in overflow-hidden">
      <header className="border-b border-line px-5 pb-4 pt-4">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <h2 className="text-[15px] font-semibold">{r.question}</h2>
          {modeBadge}
        </div>
        {r.intent && r.intent !== r.question && <p className="text-xs text-ink-muted">Interpreted as: {r.intent}</p>}
      </header>

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-4 p-5">
          {scalar && (
            <p className="text-4xl font-semibold tracking-tight tabular-nums text-ink">
              {fmt(scalar.value)}
              <span className="ml-2 text-sm font-normal text-ink-muted">{scalar.label}</span>
            </p>
          )}
          <p className="max-w-[70ch] text-[15px] leading-relaxed text-ink">{r.answer}</p>
          <Warnings items={r.warnings} />
          <ResultChart chart={r.chart} />
        </div>

        <div className="border-t border-line bg-surface-2 p-5 lg:border-l lg:border-t-0" role="group" aria-label="How this was computed">
          <p className="mb-3 text-sm font-semibold text-lens-deep">How this was computed</p>
          <ol className="space-y-3">
            {r.steps.map((s, i) => (
              <li key={i} className="receipt-step relative flex gap-3 text-[13px] leading-snug text-ink-soft">
                <span className="relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-lens/40 bg-surface text-[11px] font-semibold text-lens-deep">
                  {i + 1}
                </span>
                <span className="pt-0.5">{s}</span>
              </li>
            ))}
          </ol>
          <p className="mt-4 text-xs text-ink-muted">
            Calculated with Pandas on {r.rows_total.toLocaleString()} rows. The AI only chooses the operation; it never supplies the numbers.
          </p>
          <button className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-lens-deep hover:underline" onClick={() => setShowJson((v) => !v)} aria-expanded={showJson}>
            <Braces className="h-3.5 w-3.5" aria-hidden /> {showJson ? "Hide" : "Show"} the exact operation
          </button>
          {showJson && (
            <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-code p-3 font-mono text-[11px] leading-relaxed text-code-fg">
              {JSON.stringify(r.operation, null, 2)}
            </pre>
          )}
        </div>
      </div>

      {(result?.rows.length || r.evidence) && (
        <footer className="border-t border-line px-5 pb-5 pt-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-1" role="tablist">
              <TabButton active={tab === "result"} onClick={() => setTab("result")} icon={<Table2 className="h-3.5 w-3.5" />}>
                Result table
              </TabButton>
              {r.evidence && (
                <TabButton active={tab === "evidence"} onClick={() => setTab("evidence")} icon={<Table2 className="h-3.5 w-3.5" />}>
                  Evidence rows ({r.evidence.total_matching.toLocaleString()})
                </TabButton>
              )}
            </div>
            {tab === "result" && result && result.rows.length > 0 && (
              <button className="btn-quiet py-1.5 text-xs" onClick={() => downloadCsv(`${stem}.csv`, result.columns, result.rows)}>
                <Download className="h-3.5 w-3.5" aria-hidden /> Export CSV
              </button>
            )}
          </div>
          {tab === "result" && result && <DataTable columns={result.columns} rows={result.rows} maxHeight="20rem" dense label="Result table" />}
          {tab === "evidence" && r.evidence && (
            <>
              <p className="mb-2 text-xs text-ink-muted">
                {r.evidence.note}. Showing up to {r.evidence.rows.length} rows straight from your data.
              </p>
              <DataTable columns={r.evidence.columns} rows={r.evidence.rows} maxHeight="20rem" dense label="Evidence rows" />
            </>
          )}
        </footer>
      )}
    </article>
  );
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium ${active ? "bg-ink text-canvas" : "text-ink-muted hover:bg-canvas hover:text-ink"}`}
    >
      {icon}
      {children}
    </button>
  );
}
