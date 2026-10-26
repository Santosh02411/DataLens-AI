import type { Cell, Row } from "./types";

export function fmt(v: Cell | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    if (Number.isInteger(v)) return v.toLocaleString("en-US");
    const d = Math.abs(v) >= 1 ? digits : 4;
    return v.toLocaleString("en-US", { maximumFractionDigits: d });
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  return v;
}

export function compact(v: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function csvCell(v: Cell): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  // Neutralise spreadsheet formula injection when the CSV is opened in Excel.
  const safe = /^[=+\-@\t\r]/.test(s) && !/^-?\d/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function downloadCsv(filename: string, columns: string[], rows: Row[]) {
  const lines = [columns.map((c) => csvCell(c)).join(","), ...rows.map((r) => columns.map((c) => csvCell(r[c])).join(","))];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const TYPE_LABEL: Record<string, string> = {
  numeric: "Number",
  datetime: "Date",
  boolean: "Yes / no",
  categorical: "Category",
  text: "Text",
  identifier: "ID",
};
