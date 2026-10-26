import { BarChart3, CalendarRange, Code2, Gauge, LineChart, MapPin, Package, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { compact, fmt } from "../format";
import type { AnalysisResult, FilterSpec, Profile } from "../types";
import { ResultChart } from "./ResultChart";

type Tile = { loading: boolean; error: string | null; result: AnalysisResult | null; ms: number | null };
const GROUP = /region|country|state|city|market|segment|channel/i;
const CATEGORY = /category|product|type|segment|department/i;

function pick(profile: Profile) {
  const nums = profile.column_profiles.filter((c) => c.type === "numeric");
  const metric = (nums.find((c) => /revenue|sales|amount|total/i.test(c.name)) ?? nums.find((c) => /price|cost|value/i.test(c.name)) ?? nums[0])?.name ?? null;
  const date = profile.column_profiles.find((c) => c.type === "datetime");
  const cats = profile.column_profiles.filter((c) => (c.type === "categorical" || c.type === "boolean") && c.unique >= 2 && c.unique <= 30);
  const cat1 = cats.find((c) => GROUP.test(c.name)) ?? cats[0];
  const cat2 = cats.find((c) => c !== cat1 && CATEGORY.test(c.name)) ?? cats.find((c) => c !== cat1);
  return { metric, date: date?.name ?? null, dateMax: (date?.stats?.max as string | undefined) ?? null, dateMin: (date?.stats?.min as string | undefined) ?? null, cat1, cat2 };
}

function shift(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Live dashboard: every tile is a real, allowlisted operation run on the backend with the shared filters. */
export function LiveDashboard({ datasetId, profile }: { datasetId: string; profile: Profile }) {
  const cfg = useMemo(() => pick(profile), [profile]);
  const [range, setRange] = useState<"all" | "30" | "90" | "180">("all");
  const [v1, setV1] = useState("");
  const [v2, setV2] = useState("");
  const [tiles, setTiles] = useState<Record<string, Tile>>({});

  const filters = useMemo<FilterSpec[]>(() => {
    const f: FilterSpec[] = [];
    if (cfg.date && cfg.dateMax && range !== "all") f.push({ column: cfg.date, op: "between", value: [shift(cfg.dateMax, Number(range) - 1), cfg.dateMax] });
    if (cfg.cat1 && v1) f.push({ column: cfg.cat1.name, op: "eq", value: v1 });
    if (cfg.cat2 && v2) f.push({ column: cfg.cat2.name, op: "eq", value: v2 });
    return f;
  }, [cfg, range, v1, v2]);

  const ops = useMemo(() => {
    const m = cfg.metric;
    const o: Record<string, Record<string, unknown>> = {
      rows: { type: "aggregate", agg: "count", column: null, filters },
    };
    if (m) {
      o.total = { type: "aggregate", agg: "sum", column: m, filters };
      o.avg = { type: "aggregate", agg: "mean", column: m, filters };
      if (cfg.cat1) o.leader = { type: "aggregate", agg: "sum", column: m, group_by: [cfg.cat1.name], sort: "desc", limit: 15, filters };
      if (cfg.date) o.trend = { type: "trend", date_column: cfg.date, agg: "sum", value_column: m, granularity: range === "30" ? "day" : range === "90" ? "week" : "month", filters };
      if (cfg.cat2) o.breakdown = { type: "aggregate", agg: "sum", column: m, group_by: [cfg.cat2.name], sort: "desc", limit: 12, filters };
    }
    return o;
  }, [cfg, filters, range]);

  useEffect(() => {
    let cancelled = false;
    setTiles((t) => Object.fromEntries(Object.keys(ops).map((k) => [k, { ...(t[k] ?? { result: null, ms: null }), loading: true, error: null }])));
    Object.entries(ops).forEach(([k, op]) => {
      const t0 = performance.now();
      api.run(datasetId, op, `Dashboard: ${k}`, false)
        .then((r) => !cancelled && setTiles((t) => ({ ...t, [k]: { loading: false, error: null, result: r, ms: Math.round(performance.now() - t0) } })))
        .catch((e) => !cancelled && setTiles((t) => ({ ...t, [k]: { loading: false, error: e?.message ?? "Failed", result: null, ms: Math.round(performance.now() - t0) } })));
    });
    return () => { cancelled = true; };
  }, [datasetId, JSON.stringify(ops)]); // eslint-disable-line react-hooks/exhaustive-deps

  const scalar = (k: string) => tiles[k]?.result?.result?.scalar?.value as number | undefined;
  const leader = tiles.leader?.result?.result?.rows?.[0];
  const m = cfg.metric;
  const active = filters.length;

  return (
    <section aria-label="Live dashboard" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Live dashboard</h2>
          <p className="text-sm text-ink-muted">Every number below is computed on the server from your data{active ? ` with ${active} filter${active > 1 ? "s" : ""} applied` : ""}.</p>
        </div>
        {active > 0 && <button className="text-sm font-medium text-lens-deep hover:underline" onClick={() => { setRange("all"); setV1(""); setV2(""); }}>Clear filters</button>}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <FilterCard icon={CalendarRange} title="Date range">
          {cfg.date ? (
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Date range">
              {(["all", "30", "90", "180"] as const).map((r) => (
                <button key={r} role="radio" aria-checked={range === r} onClick={() => setRange(r)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium ring-1 ${range === r ? "brand-bg text-white ring-transparent" : "bg-surface-2 text-ink-soft ring-line hover:text-ink"}`}>
                  {r === "all" ? "All" : `Last ${r}d`}
                </button>
              ))}
              <p className="mt-1 w-full text-xs text-ink-muted">Data covers {cfg.dateMin} to {cfg.dateMax}; ranges end on the last date in the data.</p>
            </div>
          ) : <p className="text-sm text-ink-muted">No date column in this dataset.</p>}
        </FilterCard>
        <FilterCard icon={MapPin} title={cfg.cat1?.name ?? "Group"}>
          {cfg.cat1 ? <ValueSelect label={cfg.cat1.name} value={v1} onChange={setV1} options={cfg.cat1.top_values?.map((t) => t.value) ?? []} /> : <p className="text-sm text-ink-muted">No category column.</p>}
        </FilterCard>
        <FilterCard icon={Package} title={cfg.cat2?.name ?? "Category"}>
          {cfg.cat2 ? <ValueSelect label={cfg.cat2.name} value={v2} onChange={setV2} options={cfg.cat2.top_values?.map((t) => t.value) ?? []} /> : <p className="text-sm text-ink-muted">No second category column.</p>}
        </FilterCard>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {m && <Kpi icon={Gauge} title={`Total ${m}`} tile={tiles.total} value={scalar("total") !== undefined ? compact(scalar("total")!) : null} exact={fmt(scalar("total") ?? null)} op="sum" />}
        <Kpi icon={BarChart3} title="Rows" tile={tiles.rows} value={scalar("rows") !== undefined ? compact(scalar("rows")!) : null} exact={fmt(scalar("rows") ?? null)} op="count" />
        {m && <Kpi icon={Gauge} title={`Average ${m}`} tile={tiles.avg} value={scalar("avg") !== undefined ? fmt(scalar("avg")!) : null} exact={fmt(scalar("avg") ?? null)} op="mean" />}
        {m && cfg.cat1 && <Kpi icon={Trophy} title={`Top ${cfg.cat1.name}`} tile={tiles.leader} value={leader ? String(leader[cfg.cat1.name]) : null} exact={leader ? `${fmt(leader[`total ${m}`] as number)} total ${m}` : ""} op="sum · group" />}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        {tiles.trend && <ChartTile icon={LineChart} title={`${m} over time`} tile={tiles.trend} />}
        {tiles.breakdown && <ChartTile icon={BarChart3} title={`${m} by ${cfg.cat2?.name}`} tile={tiles.breakdown} />}
      </div>
    </section>
  );
}

function FilterCard({ icon: Icon, title, children }: { icon: typeof Gauge; title: string; children: React.ReactNode }) {
  return (
    <div className="panel p-4">
      <p className="mb-3 flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-ink-muted" aria-hidden /> {title}</p>
      {children}
    </div>
  );
}

function ValueSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select className="field" aria-label={`Filter by ${label}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">All {label} values</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

function Meta({ tile, op }: { tile?: Tile; op: string }) {
  const rows = tile?.result?.result?.rows?.length;
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-muted">
      <Code2 className="h-3 w-3" aria-hidden /> {op}{rows !== undefined ? ` · ${rows} row${rows === 1 ? "" : "s"}` : ""}{tile?.ms != null ? ` · ${tile.ms}ms` : ""}
    </span>
  );
}

function Kpi({ icon: Icon, title, tile, value, exact, op }: { icon: typeof Gauge; title: string; tile?: Tile; value: string | null; exact: string; op: string }) {
  return (
    <div className="panel relative overflow-hidden p-4">
      <div className="brand-bg pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full opacity-[0.12] blur-2xl" aria-hidden />
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-ink-muted" aria-hidden /> {title}</p>
        <Meta tile={tile} op={op} />
      </div>
      <div className="mt-4 min-h-[2.75rem]" aria-live="polite">
        {tile?.loading && !tile.result ? <div className="h-9 w-32 animate-pulse rounded bg-surface-2" /> :
          tile?.error ? <p className="text-sm text-ink-muted">{/No rows match/.test(tile.error) ? "No matching data for these filters." : tile.error}</p> :
          <p className="brand-text truncate text-4xl font-bold tracking-tight tabular-nums" title={exact}>{value ?? "—"}</p>}
      </div>
      <p className="mt-1 truncate text-xs text-ink-muted">{tile?.error ? "" : exact}</p>
    </div>
  );
}

function ChartTile({ icon: Icon, title, tile }: { icon: typeof Gauge; title: string; tile: Tile }) {
  const r = tile.result;
  return (
    <div className="panel p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-ink-muted" aria-hidden /> {title}</p>
        <Meta tile={tile} op={String(r?.operation?.type ?? "…")} />
      </div>
      {tile.loading && !r ? <div className="h-[260px] animate-pulse rounded-lg bg-surface-2" /> :
        tile.error ? <p className="flex h-[260px] items-center justify-center text-sm text-ink-muted">{/No rows match/.test(tile.error) ? "No matching data for these filters." : tile.error}</p> :
        r ? <ResultChart chart={r.chart} height={260} /> : null}
    </div>
  );
}
