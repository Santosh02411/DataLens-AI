import { ArrowUp, Info } from "lucide-react";
import { useState } from "react";
import type { AnalysisResult, Status, Suggestion } from "../types";
import { AnswerCard } from "./AnswerCard";
import { ErrorNote, Spinner } from "./ui";

interface Props {
  status: Status | null;
  suggestions: Suggestion[];
  analyses: AnalysisResult[];
  busy: string | null;
  error: unknown;
  onAsk: (q: string) => void;
  onSuggestion: (s: Suggestion) => void;
  onDismissError: () => void;
  goToBuilder: () => void;
}

export function AskView({ status, suggestions, analyses, busy, error, onAsk, onSuggestion, onDismissError, goToBuilder }: Props) {
  const [q, setQ] = useState("");
  const ai = status?.ai.configured ?? false;
  const submit = () => {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    onAsk(text);
    setQ("");
  };

  return (
    <div className="space-y-5">
      <section className="panel p-4">
        <label htmlFor="question" className="sr-only">Ask a question about this dataset</label>
        <div className="flex items-end gap-2">
          <textarea
            id="question"
            rows={2}
            maxLength={500}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={ai ? "Ask about your data, e.g. Which product category had the highest average rating in Q4?" : "AI questions need an API key. Pick a suggested question below, or use the analysis builder."}
            className="field min-h-[3.25rem] resize-none border-0 px-1 text-[15px] focus:ring-0"
          />
          <button className="btn-primary h-10 w-10 shrink-0 p-0" onClick={submit} disabled={!!busy || q.trim().length < 3} aria-label="Ask">
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
        {!ai && (
          <p className="mt-2 flex items-start gap-2 rounded-lg bg-canvas px-3 py-2 text-xs leading-relaxed text-ink-soft">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-muted" aria-hidden />
            <span>
              Typed questions are turned into analyses by an AI model, and none is configured. Add a key to <code className="font-mono">backend/.env</code> to enable it.
              Suggested questions still run their real analysis, and the{" "}
              <button className="font-medium text-lens-deep underline" onClick={goToBuilder}>analysis builder</button> lets you build any question by hand.
            </span>
          </p>
        )}
        {suggestions.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
            {suggestions.map((s) => (
              <button
                key={s.question}
                onClick={() => onSuggestion(s)}
                disabled={!!busy}
                className="rounded-full border border-line bg-surface px-3 py-1.5 text-left text-[13px] text-ink-soft hover:border-lens/50 hover:text-ink disabled:opacity-50"
                title={s.kind}
              >
                {s.question}
              </button>
            ))}
          </div>
        )}
      </section>

      {busy && (
        <div className="panel px-5 py-4">
          <Spinner label={busy} />
        </div>
      )}
      <ErrorNote error={error} onDismiss={onDismissError} />

      {analyses.length === 0 && !busy ? (
        <div className="rounded-xl border border-dashed border-line px-6 py-14 text-center">
          <p className="font-medium">Your answers will appear here</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
            Each one shows the result, a chart, the exact calculation steps and the rows behind it. Try a suggested question to start.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {analyses.map((a, i) => (
            <AnswerCard key={`${analyses.length - i}-${a.question}`} r={a} />
          ))}
        </div>
      )}
    </div>
  );
}
