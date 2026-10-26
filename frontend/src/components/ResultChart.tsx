import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { useChartColors, type ChartColors } from "../ThemeContext";
import { compact, fmt } from "../format";
import type { ChartSpec } from "../types";

const tick = (v: unknown) => (typeof v === "number" ? compact(v) : String(v));
const tooltipFmt = (v: unknown) => (typeof v === "number" ? fmt(v) : String(v));

export function tooltipProps(c: ChartColors) {
  return {
    contentStyle: { borderRadius: 8, border: `1px solid ${c.line}`, background: c.surface, color: c.text, fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,0.12)" },
    labelStyle: { color: c.text, fontWeight: 600 },
    itemStyle: { color: c.text },
  };
}

function references(chart: ChartSpec, c: ChartColors) {
  const lines = (chart.reference_lines ?? []).map((r, k) => (
    <ReferenceLine
      key={`y-${r.label}`}
      y={r.y}
      stroke={r.label === "Median" || r.label === "Overall" ? c.muted : c.caution}
      strokeDasharray="4 4"
      ifOverflow="extendDomain"
      label={{ value: `${r.label} ${fmt(r.y)}`, position: "right", fontSize: 11, fill: c.muted, dy: k === 0 ? -6 : 6 }}
    />
  ));
  if (chart.highlight_x)
    lines.push(
      <ReferenceLine key="hx" x={chart.highlight_x} stroke={c.caution} strokeDasharray="4 4" label={{ value: "Unusual", position: "insideTop", fontSize: 11, fill: c.caution }} />,
    );
  return lines;
}

export function chartSummary(chart: ChartSpec): string {
  const kind = chart.type === "histogram" ? "Histogram" : `${chart.type[0].toUpperCase()}${chart.type.slice(1)} chart`;
  const series = (chart.series ?? []).join(", ");
  const refs = (chart.reference_lines ?? []).map((r) => `${r.label} at ${fmt(r.y)}`).join("; ");
  return `${kind} of ${series} by ${chart.x}, ${chart.data?.length ?? 0} points${refs ? `. Reference lines: ${refs}` : ""}${chart.highlight_x ? `. Highlighted: ${chart.highlight_x}` : ""}. The values are listed in the table below the chart.`;
}

/** Charts are drawn for sighted users; screen readers get a summary (the numbers are in the adjacent tables). */
export function ResultChart({ chart, height = 280 }: { chart: ChartSpec; height?: number }) {
  const colors = useChartColors();
  if (chart.type === "none" || !chart.data?.length || !chart.x) return null;
  return (
    <figure className="m-0" aria-label={chartSummary(chart)} role="figure">
      <div aria-hidden="true">
        <ChartInner chart={chart} height={height} c={colors} />
      </div>
    </figure>
  );
}

function ChartInner({ chart, height, c }: { chart: ChartSpec; height: number; c: ChartColors }) {
  if (!chart.data?.length || !chart.x) return null;
  const axis = { fontSize: 12, fill: c.axis };
  const series = chart.series ?? [];
  const many = chart.data.length > 8;
  const label = chart.data.map((d) => String(d[chart.x!] ?? "")).reduce((m, s) => Math.max(m, s.length), 0);
  const rotate = many || label > 12;
  const tp = tooltipProps(c);
  const refMargin = chart.reference_lines?.length ? 96 : 16;

  if (chart.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chart.data} margin={{ top: 16, right: refMargin, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey={chart.x} tick={axis} tickLine={false} axisLine={{ stroke: c.line }} />
          <YAxis tick={axis} tickFormatter={tick} tickLine={false} axisLine={false} width={56} />
          <Tooltip formatter={tooltipFmt} {...tp} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: c.text }} />}
          {references(chart, c)}
          {series.map((s, i) => (
            <Line key={s} type="monotone" dataKey={s} stroke={c.series[i % c.series.length]} strokeWidth={2.25} dot={{ r: 2.5 }} activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (chart.type === "scatter") {
    const y = series[0];
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
          <CartesianGrid stroke={c.grid} />
          <XAxis type="number" dataKey={chart.x} name={chart.x} tick={axis} tickFormatter={tick} stroke={c.line} label={{ value: chart.x, position: "insideBottom", offset: -10, fontSize: 12, fill: c.axis }} />
          <YAxis type="number" dataKey={y} name={y} tick={axis} tickFormatter={tick} width={56} stroke={c.line} label={{ value: y, angle: -90, position: "insideLeft", fontSize: 12, fill: c.axis }} />
          <Tooltip formatter={tooltipFmt} {...tp} cursor={{ strokeDasharray: "3 3", stroke: c.muted }} />
          <Scatter data={chart.data} fill={c.series[0]} fillOpacity={0.5} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chart.data} margin={{ top: 8, right: refMargin, bottom: rotate ? 40 : 4, left: 0 }} barCategoryGap={chart.type === "histogram" ? 1 : "22%"}>
        <CartesianGrid stroke={c.grid} vertical={false} />
        <XAxis dataKey={chart.x} tick={axis} tickLine={false} axisLine={{ stroke: c.line }} interval={many ? "preserveStartEnd" : 0} angle={rotate ? -35 : 0} textAnchor={rotate ? "end" : "middle"} />
        <YAxis tick={axis} tickFormatter={tick} tickLine={false} axisLine={false} width={56} />
        <Tooltip formatter={tooltipFmt} {...tp} cursor={{ fill: c.cursor }} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: c.text }} verticalAlign="top" height={28} />}
        {references(chart, c)}
        {series.map((s, i) => (
          <Bar key={s} dataKey={s} fill={c.series[i % c.series.length]} radius={chart.type === "histogram" ? 0 : [4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
