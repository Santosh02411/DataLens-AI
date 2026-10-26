import { ChevronLeft, ChevronRight, Columns3, Filter, Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { fmt } from "../format";
import type { FilterSpec, Profile, RecordDetail, Row, RowsQuery } from "../types";
import { DataTable } from "./DataTable";
import { ErrorNote, Spinner, TypeBadge } from "./ui";

const OPS: [string, string][] = [["eq", "is"], ["ne", "is not"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["contains", "contains"], ["is_null", "is missing"], ["not_null", "is present"]];
const OP_LABEL: Record<string, string> = { ...Object.fromEntries(OPS), between: "between", in: "is one of", not_in: "is not one of" };
const PAGE = 50;

export function describeFilter(f: FilterSpec): string {
  const v = Array.isArray(f.value) ? (f.op === "between" ? f.value.map(fmt).join(" – ") : f.value.map(fmt).join(", ")) : f.op === "is_null" || f.op === "not_null" ? "" : fmt(f.value as never);
  return `${f.column} ${OP_LABEL[f.op] ?? f.op} ${v}`.trim();
}

interface Props {
  datasetId: string;
  profile: Profile;
  initialFilters?: FilterSpec[];
  drillColumns?: string[];
  focusMetric?: string | null;
  title?: string;
}

export function RecordExplorer({ datasetId, profile, initialFilters = [], drillColumns = [], focusMetric, title }: Props) {
  const all = profile.column_profiles.map((c) => c.name);
  const [filters, setFilters] = useState<FilterSpec[]>(initialFilters);
  const [visible, setVisible] = useState<string[]>(all.slice(0, 10));
  const [sort, setSort] = useState<{ column: string; order: "asc" | "desc" } | null>(focusMetric ? { column: focusMetric, order: "desc" } : null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState<RowsQuery | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [inspect, setInspect] = useState<number | null>(null);
  const [showCols, setShowCols] = useState(false);
  const [adding, setAdding] = useState(false);

  useEffect(() => { setFilters(initialFilters); setOffset(0); }, [JSON.stringify(initialFilters)]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => { setSearch(query.trim()); setOffset(0); }, 300); return () => clearTimeout(t); }, [query]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.query(datasetId, { filters, sort: sort?.column, order: sort?.order, offset, limit: PAGE, search: search || undefined, columns: visible })
      .then((p) => { if (!cancelled) { setPage(p); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [datasetId, JSON.stringify(filters), sort, offset, search, visible.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const topValues = (c: string) => profile.column_profiles.find((p) => p.name === c)?.top_values?.map((t) => t.value) ?? [];
  const drill = drillColumns.filter((c) => !filters.some((f) => f.column === c && f.op === "eq"));
  const total = page?.total ?? 0;

  return (
    <section className="panel p-5" aria-label={title ?? "Record explorer"}>
      {title && <h2 className="mb-3 text-[15px] font-semibold">{title}</h2>}
      <div className="flex flex-wrap items-center gap-2">
        {filters.length === 0 && <span className="text-sm text-ink-muted">All rows</span>}
        {filters.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded-full bg-lens-soft py-1 pl-3 pr-1 text-[13px] text-lens-deep ring-1 ring-lens/25">
            <Filter className="h-3 w-3" aria-hidden /> {describeFilter(f)}
            <button className="rounded-full p-0.5 hover:bg-lens/15" aria-label={`Remove filter ${describeFilter(f)}`} onClick={() => { setFilters(filters.filter((_, k) => k !== i)); setOffset(0); }}>
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        ))}
        {filters.length < 8 && (
          <button className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-medium text-lens-deep ring-1 ring-line hover:bg-surface-2" onClick={() => setAdding((v) => !v)} aria-expanded={adding}>
            <Plus className="h-3.5 w-3.5" aria-hidden /> Add filter
          </button>
        )}
        {JSON.stringify(filters) !== JSON.stringify(initialFilters) && (
          <button className="text-xs font-medium text-ink-muted underline hover:text-ink" onClick={() => { setFilters(initialFilters); setOffset(0); }}>Reset filters</button>
        )}
      </div>
      {adding && <FilterForm columns={all} topValues={topValues} onAdd={(f) => { setFilters([...filters, f]); setAdding(false); setOffset(0); }} onCancel={() => setAdding(false)} />}

      {drill.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
          <span className="text-ink-muted">Drill down:</span>
          {drill.slice(0, 2).map((c) => (
            <span key={c} className="inline-flex flex-wrap items-center gap-1.5">
              <span className="font-medium text-ink-soft">{c}</span>
              {topValues(c).slice(0, 5).map((v) => (
                <button key={v} className="rounded-md bg-surface-2 px-2 py-0.5 text-ink-soft ring-1 ring-line hover:text-ink hover:ring-lens/40"
                  onClick={() => { setFilters([...filters, { column: c, op: "eq", value: v }]); setOffset(0); }}>{v}</button>
              ))}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <label className="relative w-full max-w-xs">
          <span className="sr-only">Search rows</span>
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-muted" aria-hidden />
          <input className="field pl-9" placeholder="Search text columns" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
          {loading && <Spinner />}
          <span className="tabular-nums" aria-live="polite">
            {total ? `${(offset + 1).toLocaleString()}–${Math.min(offset + PAGE, total).toLocaleString()} of ${total.toLocaleString()}` : "0 rows"}
            {page && filters.length > 0 ? ` (filtered from ${page.dataset_rows.toLocaleString()})` : ""}
          </span>
          <button className="btn-quiet px-2 py-1.5" onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
          <button className="btn-quiet px-2 py-1.5" onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= total} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
          <div className="relative">
            <button className="btn-quiet px-2.5 py-1.5 text-xs" onClick={() => setShowCols((v) => !v)} aria-expanded={showCols} aria-haspopup="true">
              <Columns3 className="h-4 w-4" aria-hidden /> Columns ({visible.length})
            </button>
            {showCols && (
              <div className="absolute right-0 z-30 mt-1 max-h-72 w-56 overflow-auto rounded-lg bg-surface p-2 shadow-panel ring-1 ring-line" role="group" aria-label="Visible columns">
                <div className="mb-1 flex justify-between px-1 text-xs">
                  <button className="text-lens-deep hover:underline" onClick={() => setVisible(all)}>All</button>
                  <button className="text-lens-deep hover:underline" onClick={() => setVisible(all.slice(0, 1))}>None</button>
                </div>
                {profile.column_profiles.map((c) => (
                  <label key={c.name} className="flex cursor-pointer items-center justify-between gap-2 rounded px-1.5 py-1 text-[13px] text-ink-soft hover:bg-surface-2">
                    <span className="flex items-center gap-2">
                      <input type="checkbox" className="accent-[rgb(var(--lens))]" checked={visible.includes(c.name)}
                        onChange={(e) => setVisible(e.target.checked ? all.filter((n) => n === c.name || visible.includes(n)) : visible.filter((n) => n !== c.name).length ? visible.filter((n) => n !== c.name) : visible)} />
                      {c.name}
                    </span>
                    <TypeBadge type={c.type} />
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="mt-3">
        <ErrorNote error={error} />
        {page && (
          <DataTable columns={page.columns} rows={page.rows as Row[]} maxHeight="30rem" dense label={`${title ?? "Records"}: table (${total.toLocaleString()} rows)`}
            sort={sort} onSort={(c) => { setOffset(0); setSort((s) => (s?.column === c ? (s.order === "asc" ? { column: c, order: "desc" } : null) : { column: c, order: "asc" })); }}
            onRowClick={(r) => setInspect(Number((r as Row & { _row: number })._row))} />
        )}
      </div>
      <p className="mt-2 text-xs text-ink-muted">Select a row to inspect every field. Select a column header to sort.</p>
      {inspect !== null && <RecordDrawer datasetId={datasetId} row={inspect} onClose={() => setInspect(null)} />}
    </section>
  );
}

function FilterForm({ columns, topValues, onAdd, onCancel }: { columns: string[]; topValues: (c: string) => string[]; onAdd: (f: FilterSpec) => void; onCancel: () => void }) {
  const [column, setColumn] = useState(columns[0]);
  const [op, setOp] = useState("eq");
  const [value, setValue] = useState("");
  const noValue = op === "is_null" || op === "not_null";
  return (
    <form className="mt-3 grid gap-2 rounded-lg bg-surface-2 p-3 sm:grid-cols-[1fr_8rem_1fr_auto_auto]" onSubmit={(e) => {
      e.preventDefault();
      const num = value.trim() !== "" && !Number.isNaN(Number(value)) && ["gt", "gte", "lt", "lte"].includes(op);
      onAdd({ column, op, value: noValue ? null : num ? Number(value) : value });
    }}>
      <select className="field" aria-label="Filter column" value={column} onChange={(e) => setColumn(e.target.value)}>{columns.map((c) => <option key={c}>{c}</option>)}</select>
      <select className="field" aria-label="Filter condition" value={op} onChange={(e) => setOp(e.target.value)}>{OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      <input className="field" aria-label="Filter value" list="rx-values" disabled={noValue} value={value} onChange={(e) => setValue(e.target.value)} placeholder="Value" />
      <datalist id="rx-values">{topValues(column).map((v) => <option key={v} value={v} />)}</datalist>
      <button type="submit" className="btn-primary" disabled={!noValue && !value.trim()}>Apply</button>
      <button type="button" className="btn-quiet" onClick={onCancel}>Cancel</button>
    </form>
  );
}

export function RecordDrawer({ datasetId, row, onClose }: { datasetId: string; row: number; onClose: () => void }) {
  const [detail, setDetail] = useState<RecordDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { api.record(datasetId, row).then(setDetail).catch(setError); }, [datasetId, row]);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  const unusual = useMemo(() => detail?.fields.filter((f) => f.unusual) ?? [], [detail]);
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="record-title" className="h-full w-full max-w-md overflow-y-auto bg-surface p-5 shadow-panel" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="record-title" className="text-lg font-semibold">Record {row + 1}</h2>
            <p className="text-xs text-ink-muted">Every field, with where each number sits in the dataset.</p>
          </div>
          <button ref={closeRef} className="btn-quiet px-2 py-1.5" onClick={onClose} aria-label="Close record"><X className="h-4 w-4" /></button>
        </div>
        <ErrorNote error={error} />
        {!detail && !error && <Spinner label="Loading record" />}
        {detail && (
          <>
            {unusual.length > 0 && (
              <p className="mb-3 rounded-lg bg-caution-soft px-3 py-2 text-sm text-ink-soft">
                Statistically unusual in: <strong className="text-ink">{unusual.map((u) => u.column).join(", ")}</strong>. Unusual isn't the same as wrong.
              </p>
            )}
            {detail.exact_copies ? <p className="mb-3 text-sm text-ink-soft">This row has {detail.exact_copies} exact {detail.exact_copies === 1 ? "copy" : "copies"} elsewhere in the data.</p> : null}
            <dl className="divide-y divide-line">
              {detail.fields.map((f) => (
                <div key={f.column} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] items-start gap-x-3 py-2.5">
                  <dt className="flex items-center gap-2 text-sm text-ink-muted">{f.column} <TypeBadge type={f.type} /></dt>
                  <dd className="text-right">
                    <span className={`text-sm font-medium tabular-nums ${f.value === null ? "text-ink-muted" : ""}`}>{f.value === null ? "missing" : fmt(f.value)}</span>
                    {f.percentile !== undefined && (
                      <span className="mt-1.5 flex items-center gap-2 text-[11px] text-ink-muted">
                        <span className="relative h-1.5 flex-1 rounded-full bg-surface-2" role="img" aria-label={`Percentile ${f.percentile}`}>
                          <span className={`absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded ${f.unusual ? "bg-caution" : "bg-lens"}`} style={{ left: `calc(${f.percentile}% - 2px)` }} />
                        </span>
                        <span className="whitespace-nowrap">{f.percentile}th pct · median {fmt(f.median ?? null)}</span>
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-xs text-ink-muted">{detail.note}</p>
          </>
        )}
      </div>
    </div>
  );
}
