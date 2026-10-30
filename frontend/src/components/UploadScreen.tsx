import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import type { Status } from "../types";
import { browserEngine } from "../api";
import { ThemeToggle } from "../ThemeContext";
import { ErrorNote, Spinner } from "./ui";

interface Props {
  status: Status | null;
  busy: string | null;
  error: unknown;
  onUpload: (file: File) => void;
  onSample: () => void;
  onRetry: () => void;
}

const ACCEPT = ".csv,.tsv,.txt,.xlsx,.xlsm";

export function UploadScreen({ status, busy, error, onUpload, onSample, onRetry }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const limits = status?.limits;

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-5 py-12">
      <div className="mb-10 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <span className="text-lg font-semibold tracking-tight">DataLens AI</span>
        </div>
        <ThemeToggle tone="page" />
      </div>

      <div className="grid items-start gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <h1 className="max-w-[18ch] text-[2.6rem] font-semibold leading-[1.08] tracking-tight text-ink">
            Ask your spreadsheet a question. Check every answer.
          </h1>
          <p className="mt-5 max-w-[52ch] text-[17px] leading-relaxed text-ink-soft">
            DataLens turns plain-English questions into safe, verifiable calculations. Each answer comes with the method, the rows behind it,
            and a warning when the data is too thin to trust.
          </p>
          <ol className="mt-8 space-y-4">
            {[
              ["Upload a CSV or Excel file", "It's checked, typed and profiled for quality issues right away."],
              ["Discover and investigate", "DataLens finds trends, unusual values and changes, then lets you verify each one down to the rows."],
              ["Ask and simulate", "Ask in plain English, or run what-if scenarios. Every number is computed, never generated."],
            ].map(([t, d], i) => (
              <li key={t} className="flex gap-3.5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold text-canvas">{i + 1}</span>
                <div>
                  <p className="font-medium">{t}</p>
                  <p className="text-sm text-ink-muted">{d}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="space-y-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => !busy && input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              const f = e.dataTransfer.files?.[0];
              if (f && !busy) onUpload(f);
            }}
            className={`panel flex cursor-pointer flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-12 text-center transition-colors ${
              drag ? "border-lens bg-lens-soft" : "border-line hover:border-lens/60"
            }`}
          >
            {busy ? (
              <Spinner label={busy} />
            ) : (
              <>
                <UploadCloud className="h-9 w-9 text-lens" aria-hidden />
                <p className="text-base font-semibold">Drop a file here, or click to browse</p>
                <p className="text-sm text-ink-muted">
                  CSV, TSV or Excel (.xlsx){limits ? ` · up to ${limits.max_upload_mb} MB and ${limits.max_rows.toLocaleString()} rows` : ""}
                </p>
              </>
            )}
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
          </div>

          <button className="btn-quiet w-full py-3" onClick={onSample} disabled={!!busy || status?.sample_available === false}>
            <FileSpreadsheet className="h-4 w-4 text-lens" aria-hidden />
            Try the sample retail sales data
          </button>

          {status && !status.ai.configured && (
            <p className="rounded-lg bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-muted ring-1 ring-line">
              AI question answering is off because no API key is configured. Data health, insights, suggested analyses and the analysis builder all work
              without it.{" "}
              {browserEngine.active() && <button className="font-medium text-lens-deep underline" onClick={browserEngine.promptForKey}>Use my own free Gemini key</button>}
            </p>
          )}
          <ErrorNote error={error} />
          {!status && error && !busy ? (
            <button className="btn-quiet w-full" onClick={onRetry}>
              Check the server again
            </button>
          ) : null}
        </div>
      </div>
    </main>
  );
}
