import { AlertTriangle, Info, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "../api";
import { TYPE_LABEL } from "../format";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin text-lens" aria-hidden />
      {label}
    </span>
  );
}

export function ErrorNote({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  const message = e?.message ?? (error instanceof Error ? error.message : String(error));
  const details = e?.details.filter((d) => d !== message) ?? [];
  if (e?.code === "ai_not_configured") {
    return (
      <div className="flex gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm" role="status">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">AI question answering isn't set up, so this question wasn't sent anywhere.</p>
          <p className="mt-0.5 text-ink-soft">{message}</p>
        </div>
        {onDismiss && (
          <button className="text-xs font-medium text-ink-muted hover:text-ink" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="flex gap-3 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-sm" role="alert">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{message}</p>
        {details.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-soft">
            {details.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        )}
      </div>
      {onDismiss && (
        <button className="text-xs font-medium text-ink-muted hover:text-ink" onClick={onDismiss}>
          Dismiss
        </button>
      )}
    </div>
  );
}

export function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="rounded-lg border border-caution/25 bg-caution-soft px-3.5 py-2.5">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-caution">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> Read with care
      </p>
      <ul className="space-y-0.5 text-sm text-ink-soft">
        {items.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

const TYPE_STYLE: Record<string, string> = {
  numeric: "bg-lens-soft text-lens-deep",
  datetime: "bg-t-date text-t-date-fg",
  categorical: "bg-t-cat text-t-cat-fg",
  boolean: "bg-t-bool text-t-bool-fg",
  text: "bg-canvas text-ink-muted",
  identifier: "bg-canvas text-ink-muted",
};

export function TypeBadge({ type }: { type: string }) {
  return <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${TYPE_STYLE[type] ?? TYPE_STYLE.text}`}>{TYPE_LABEL[type] ?? type}</span>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <h2 className="text-[15px] font-semibold text-ink">{children}</h2>
      {aside}
    </div>
  );
}

export function SeverityDot({ severity }: { severity: "high" | "medium" | "low" }) {
  const cls = severity === "high" ? "bg-danger" : severity === "medium" ? "bg-caution" : "bg-ink-muted/50";
  return <span role="img" className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${cls}`} aria-label={`${severity} severity`} />;
}
