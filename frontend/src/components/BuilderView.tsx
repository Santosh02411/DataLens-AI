import { Play, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { DatasetSummary, Profile } from "../types";
import { Spinner } from "./ui";

type Kind = "aggregate" | "trend" | "period_change" | "correlation" | "distribution" | "top_rows";
interface FilterRow { column: string; op: string; value: string }

const KINDS: { id: Kind; label: string; hint: string }[] = [
  { id: "aggregate", label: "Compare groups", hint: "Total, average, count… for each group" },
  { id: "trend", label: "Trend over time", hint: "A value by day, week, month, quarter or year" },
  { id: "period_change", label: "Change between periods", hint: "Which group rose or fell the most" },
  { id: "correlation", label: "Relationship", hint: "Do two numbers move together?" },
  { id: "distribution", label: "Distribution", hint: "How values are spread out" },
  { id: "top_rows", label: "Top rows", hint: "Rows with the highest or lowest value" },
];
const AGGS = [["sum", "Total"], ["mean", "Average"], ["median", "Median"], ["count", "Count"], ["min", "Minimum"], ["max", "Maximum"], ["nunique", "Distinct values"]];
const FILTER_OPS = [["eq", "is"], ["ne", "is not"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["contains", "contains"], ["is_null", "is missing"], ["not_null", "is present"]];

function periodsBetween(min: string, max: string, g: "month" | "quarter" | "year"): string[] {
  const a = new Date(min), b = new Date(max);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return [];
  const out: string[] = [];
  if (g === "year") for (let y = a.getUTCFullYear(); y <= b.getUTCFullYear(); y++) out.push(String(y));
  if (g === "quarter") {
    for (let y = a.getUTCFullYear(); y <= b.getUTCFullYear(); y++)
      for (let q = 1; q <= 4; q++) {
        const startQ = Math.floor(a.getUTCMonth() / 3) + 1, endQ = Math.floor(b.getUTCMonth() / 3) + 1;
        if ((y === a.getUTCFullYear() && q < startQ) || (y === b.getUTCFullYear() && q > endQ)) continue;
        out.push(`${y}-Q${q}`);
      }
  }
  if (g === "month") {
    const d = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), 1));
    while (d <= b && out.length < 240) {
      out.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`);
      d.setUTCMonth(d.getUTCMonth() + 1);
    }
  }
  return out;
}

interface Props {
  dataset: DatasetSummary;
  profile: Profile;
  busy: boolean;
  onRun: (operation: Record<string, unknown>, label: string) => void;
}

export function BuilderView({ dataset, profile, busy, onRun }: Props) {
  const cols = dataset.columns;
  const numeric = cols.filter((c) => c.type === "numeric").map((c) => c.name);
  const dates = cols.filter((c) => c.type === "datetime").map((c) => c.name);
  const groups = cols.filter((c) => ["categorical", "boolean", "text"].includes(c.type)).map((c) => c.name);
  const all = cols.map((c) => c.name);
  const metric =
    numeric.find((c) => /revenue|sales|amount|total/i.test(c)) ?? numeric.find((c) => /price|cost|value|spend/i.test(c)) ?? numeric[0] ?? "";

  const [kind, setKind] = useState<Kind>("aggregate");
  const [agg, setAgg] = useState("sum");
  const [value, setValue] = useState(metric);
  const [groupBy, setGroupBy] = useState(groups[0] ?? "");
  const [dateCol, setDateCol] = useState(dates[0] ?? "");
  const [gran, setGran] = useState<"day" | "week" | "month" | "quarter" | "year">("month");
  const [pGran, setPGran] = useState<"month" | "quarter" | "year">("quarter");
  const [pA, setPA] = useState("");
  const [pB, setPB] = useState("");
  const [x, setX] = useState(numeric[0] ?? "");
  const [y, setY] = useState(numeric[1] ?? "");
  const [distCol, setDistCol] = useState(metric || all[0]);
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const [sortBy, setSortBy] = useState(metric || dates[0] || "");
  const [changeOrder, setChangeOrder] = useState<"asc" | "desc">("asc");
  const [splitBy, setSplitBy] = useState("");
  const [n, setN] = useState(10);
  const [filters, setFilters] = useState<FilterRow[]>([]);

  const dateStats = profile.column_profiles.find((c) => c.name === dateCol)?.stats;
  const periods = useMemo(
    () => (dateStats?.min && dateStats?.max ? periodsBetween(String(dateStats.min), String(dateStats.max), pGran) : []),
    [dateStats?.min, dateStats?.max, pGran],
  );
  const topValues = (col: string) => profile.column_profiles.find((c) => c.name === col)?.top_values?.map((t) => t.value) ?? [];

  const needsValue = agg !== "count";
  const unavailable =
    (kind === "trend" || kind === "period_change") && !dates.length ? "This dataset has no date column."
    : kind === "correlation" && numeric.length < 2 ? "This needs at least two number columns."
    : kind === "top_rows" && !numeric.length && !dates.length ? "This needs a number or date column."
    : null;
  const periodNote = kind === "period_change" && periods.length < 2 ? `The dates cover only one ${pGran}. Pick a smaller period size.` : null;

  function build(): [Record<string, unknown>, string] {
    const f = filters
      .filter((r) => r.column)
      .map((r) => {
        const isNum = numeric.includes(r.column);
        const v = r.op === "is_null" || r.op === "not_null" ? null : isNum && r.value !== "" && !Number.isNaN(Number(r.value)) ? Number(r.value) : r.value;
        return { column: r.column, op: r.op, value: v };
      });
    const aggName = AGGS.find((a) => a[0] === agg)?.[1].toLowerCase() ?? agg;
    const metric = needsValue ? `${aggName} ${value}` : "number of rows";
    const where = f.length ? ` (${f.length} filter${f.length > 1 ? "s" : ""})` : "";
    switch (kind) {
      case "aggregate":
        return [{ type: "aggregate", agg, column: needsValue ? value : null, group_by: groupBy ? [groupBy] : [], filters: f, sort: order, limit: 20 },
          `${metric[0].toUpperCase()}${metric.slice(1)}${groupBy ? ` by ${groupBy}` : ""}${where}`];
      case "trend":
        return [{ type: "trend", date_column: dateCol, agg, value_column: needsValue ? value : null, granularity: gran, group_by: splitBy || null, filters: f },
          `${metric[0].toUpperCase()}${metric.slice(1)} by ${gran}${splitBy ? ` and ${splitBy}` : ""}${where}`];
      case "period_change":
        return [{ type: "period_change", date_column: dateCol, agg, value_column: needsValue ? value : null, granularity: pGran, period_a: pA || periods[periods.length - 2], period_b: pB || periods[periods.length - 1], group_by: groupBy || null, sort: changeOrder, filters: f },
          `Change in ${metric} from ${pA || periods[periods.length - 2]} to ${pB || periods[periods.length - 1]}${groupBy ? ` by ${groupBy}` : ""}${where}`];
      case "correlation":
        return [{ type: "correlation", column_x: x, column_y: y, method: "pearson", filters: f }, `Relationship between ${x} and ${y}${where}`];
      case "distribution":
        return [{ type: "distribution", column: distCol, bins: 20, filters: f }, `Distribution of ${distCol}${where}`];
      case "top_rows":
        return [{ type: "top_rows", sort_by: sortBy, order, n, filters: f }, `${order === "desc" ? "Top" : "Bottom"} ${n} rows by ${sortBy}${where}`];
    }
  }

  const sel = (val: string, set: (v: string) => void, options: (string | [string, string])[], label: string, allowNone = false) => (
    <label className="block">
      <span className="label">{label}</span>
      <select className="field" value={val} onChange={(e) => set(e.target.value)}>
        {allowNone && <option value="">None</option>}
        {options.map((o) => {
          const [v, l] = typeof o === "string" ? [o, o] : o;
          return <option key={v} value={v}>{l}</option>;
        })}
      </select>
    </label>
  );

  return (
    <section className="panel p-5">
      <p className="mb-4 max-w-[70ch] text-sm text-ink-muted">
        Build an analysis by hand. It runs through the same validation and calculation engine as AI questions, so it works with or without an API key.
      </p>
      <div className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="radiogroup" aria-label="Analysis type">
        {KINDS.map((k) => (
          <button
            key={k.id}
            role="radio"
            aria-checked={kind === k.id}
            onClick={() => setKind(k.id)}
            className={`rounded-lg border px-3.5 py-2.5 text-left ${kind === k.id ? "border-lens bg-lens-soft/60" : "border-line hover:border-lens/40"}`}
          >
            <span className="block text-sm font-medium">{k.label}</span>
            <span className="text-xs text-ink-muted">{k.hint}</span>
          </button>
        ))}
      </div>

      {unavailable ? (
        <p className="rounded-lg bg-canvas px-4 py-3 text-sm text-ink-soft">{unavailable}</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(kind === "aggregate" || kind === "trend" || kind === "period_change") && (
              <>
                {sel(agg, setAgg, AGGS as [string, string][], "Calculate")}
                {needsValue && sel(value, setValue, agg === "nunique" ? all : agg === "min" || agg === "max" ? [...numeric, ...dates] : numeric, "Of column")}
              </>
            )}
            {kind === "aggregate" && sel(groupBy, setGroupBy, groups, "For each", true)}
            {(kind === "trend" || kind === "period_change") && sel(dateCol, setDateCol, dates, "Date column")}
            {kind === "trend" && (
              <>
                {sel(gran, (v) => setGran(v as typeof gran), [["day", "Day"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]], "Grouped by")}
                {sel(splitBy, setSplitBy, groups, "Split into lines by", true)}
              </>
            )}
            {kind === "period_change" && (
              <>
                {sel(pGran, (v) => { setPGran(v as typeof pGran); setPA(""); setPB(""); }, [["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]], "Period size")}
                {sel(pA || periods[periods.length - 2] || "", setPA, periods, "From")}
                {sel(pB || periods[periods.length - 1] || "", setPB, periods, "To")}
                {sel(groupBy, setGroupBy, groups, "For each", true)}
                {sel(changeOrder, (v) => setChangeOrder(v as typeof changeOrder), [["asc", "Biggest drop first"], ["desc", "Biggest gain first"]], "Show first")}
              </>
            )}
            {kind === "correlation" && (
              <>
                {sel(x, setX, numeric, "First number column")}
                {sel(y, setY, numeric, "Second number column")}
              </>
            )}
            {kind === "distribution" && sel(distCol, setDistCol, all.filter((c) => cols.find((k) => k.name === c)?.type !== "identifier"), "Column")}
            {kind === "top_rows" && (
              <>
                {sel(sortBy, setSortBy, [...numeric, ...dates], "Sort by")}
                {sel(order, (v) => setOrder(v as typeof order), [["desc", "Highest first"], ["asc", "Lowest first"]], "Order")}
                <label className="block">
                  <span className="label">Rows</span>
                  <input type="number" min={1} max={100} className="field" value={n} onChange={(e) => setN(Math.max(1, Math.min(100, Number(e.target.value) || 10)))} />
                </label>
              </>
            )}
            {kind === "aggregate" && sel(order, (v) => setOrder(v as typeof order), [["desc", "Highest first"], ["asc", "Lowest first"]], "Sort")}
          </div>

          <div className="mt-5 space-y-2">
            <p className="label">Filters</p>
            {filters.map((f, i) => (
              <div key={i} className="grid grid-cols-[1fr_8rem_1fr_auto] gap-2">
                <select className="field" value={f.column} aria-label="Filter column" onChange={(e) => setFilters(filters.map((r, k) => (k === i ? { ...r, column: e.target.value } : r)))}>
                  {all.map((c) => <option key={c}>{c}</option>)}
                </select>
                <select className="field" value={f.op} aria-label="Filter condition" onChange={(e) => setFilters(filters.map((r, k) => (k === i ? { ...r, op: e.target.value } : r)))}>
                  {FILTER_OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <input
                  className="field"
                  aria-label="Filter value"
                  list={`fv-${i}`}
                  disabled={f.op === "is_null" || f.op === "not_null"}
                  value={f.value}
                  placeholder={dates.includes(f.column) ? "YYYY-MM-DD" : "Value"}
                  onChange={(e) => setFilters(filters.map((r, k) => (k === i ? { ...r, value: e.target.value } : r)))}
                />
                <datalist id={`fv-${i}`}>{topValues(f.column).map((v) => <option key={v} value={v} />)}</datalist>
                <button className="btn-quiet px-2.5" onClick={() => setFilters(filters.filter((_, k) => k !== i))} aria-label="Remove filter">
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
            {filters.length < 6 && (
              <button className="inline-flex items-center gap-1 text-sm font-medium text-lens-deep hover:underline" onClick={() => setFilters([...filters, { column: groups[0] ?? all[0], op: "eq", value: "" }])}>
                <Plus className="h-4 w-4" /> Add a filter
              </button>
            )}
          </div>

          {periodNote && <p className="mt-3 text-sm text-caution">{periodNote}</p>}
          <div className="mt-6 flex items-center gap-3 border-t border-line pt-4">
            <button className="btn-primary" disabled={busy || !!periodNote} onClick={() => { const [op, label] = build(); onRun(op, label); }}>
              <Play className="h-4 w-4" /> Run analysis
            </button>
            {busy && <Spinner label="Calculating" />}
          </div>
        </>
      )}
    </section>
  );
}
