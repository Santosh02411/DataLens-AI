import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { RowsPage } from "../types";
import { DataTable } from "./DataTable";
import { ErrorNote, Spinner } from "./ui";

const PAGE = 50;

export function DataView({ datasetId }: { datasetId: string }) {
  const [page, setPage] = useState<RowsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ column: string; order: "asc" | "desc" } | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(query.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .rows(datasetId, { offset, limit: PAGE, sort: sort?.column, order: sort?.order, search: search || undefined })
      .then((p) => !cancelled && (setPage(p), setError(null)))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [datasetId, offset, sort, search]);

  const onSort = (column: string) => {
    setOffset(0);
    setSort((s) => (s?.column === column ? (s.order === "asc" ? { column, order: "desc" } : null) : { column, order: "asc" }));
  };

  const total = page?.total ?? 0;
  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <label className="relative w-full max-w-xs">
          <span className="sr-only">Search rows</span>
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-muted" aria-hidden />
          <input className="field pl-9" placeholder="Search text columns" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="flex items-center gap-3 text-sm text-ink-muted">
          {loading && <Spinner />}
          <span className="tabular-nums">
            {total ? `${(offset + 1).toLocaleString()}–${Math.min(offset + PAGE, total).toLocaleString()} of ${total.toLocaleString()}` : "0 rows"}
          </span>
          <button className="btn-quiet px-2 py-1.5" onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0} aria-label="Previous page">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button className="btn-quiet px-2 py-1.5" onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= total} aria-label="Next page">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <ErrorNote error={error} />
      {page && <DataTable columns={page.columns} rows={page.rows} sort={sort} onSort={onSort} maxHeight="calc(100vh - 16rem)" dense />}
      <p className="mt-3 text-xs text-ink-muted">Select a column header to sort; select it again to reverse or clear. Missing values sort last.</p>
    </section>
  );
}
