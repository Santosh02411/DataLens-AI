import { ArrowDown, ArrowUp } from "lucide-react";
import { fmt } from "../format";
import type { Row } from "../types";

interface Props {
  columns: string[];
  rows: Row[];
  sort?: { column: string; order: "asc" | "desc" } | null;
  onSort?: (column: string) => void;
  maxHeight?: string;
  dense?: boolean;
  label?: string;
  onRowClick?: (row: Row) => void;
}

export function DataTable({ columns, rows, sort, onSort, maxHeight = "28rem", dense, label = "Data table", onRowClick }: Props) {
  if (!rows.length) return <p className="px-1 py-6 text-center text-sm text-ink-muted">No rows to show.</p>;
  const pad = dense ? "px-3 py-1.5" : "px-3 py-2";
  return (
    <div className="overflow-auto rounded-lg border border-line" style={{ maxHeight }} tabIndex={0} role="region" aria-label={label}>
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            {columns.map((c) => {
              const active = sort?.column === c;
              const numeric = rows.some((r) => typeof r[c] === "number");
              return (
                <th key={c} scope="col" className={`whitespace-nowrap border-b border-line font-medium text-ink-muted ${pad} ${numeric ? "text-right" : "text-left"}`}>
                  {onSort ? (
                    <button className={`inline-flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`} onClick={() => onSort(c)}>
                      {c}
                      {active && (sort?.order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                    </button>
                  ) : (
                    c
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className={`border-b border-line/70 last:border-0 hover:bg-surface-2 ${onRowClick ? "cursor-pointer focus:bg-lens-soft focus:outline-none" : ""}`}
              {...(onRowClick ? { tabIndex: 0, onClick: () => onRowClick(r), onKeyDown: (e: React.KeyboardEvent) => e.key === "Enter" && onRowClick(r), "aria-label": "Inspect this record" } : {})}
            >
              {columns.map((c) => {
                const v = r[c];
                return (
                  <td key={c} className={`whitespace-nowrap ${pad} ${typeof v === "number" ? "text-right tabular-nums" : ""} ${v === null ? "text-ink-muted/60" : "text-ink"}`}>
                    {v === null ? "missing" : `${fmt(v)}${typeof v === "number" && (c.includes("%") || c === "share") ? "%" : ""}`}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
