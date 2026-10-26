export type ColumnType = "numeric" | "datetime" | "boolean" | "categorical" | "text" | "identifier";
export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;

export interface DatasetSummary {
  id: string;
  name: string;
  source: "upload" | "sample";
  created_at: string;
  rows: number;
  columns: { name: string; type: ColumnType }[];
  file: { type: string; size_bytes: number; sheet: string | null; sheets: string[]; delimiter: string | null; encoding: string | null };
  notes: string[];
}

export interface Issue {
  severity: "high" | "medium" | "low";
  column: string | null;
  title: string;
  detail: string;
}

export interface NumericStats {
  mean: number | null; std: number | null; min: number | null; q1: number | null; median: number | null;
  q3: number | null; max: number | null; sum: number | null; zeros: number; negatives: number;
  outliers: number; outlier_bounds: [number, number] | null; skew: number | null;
}

export interface ColumnProfile {
  name: string;
  type: ColumnType;
  dtype: string;
  missing: number;
  missing_pct: number;
  unique: number;
  unique_pct: number;
  sample_values: string[];
  stats?: Partial<NumericStats> & { span_days?: number; min?: number | string | null; max?: number | string | null };
  top_values?: { value: string; count: number; pct: number }[];
}

export interface Profile {
  rows: number;
  columns: number;
  missing_cells: number;
  missing_pct: number;
  duplicate_rows: number;
  duplicate_pct: number;
  quality_score: number;
  quality_formula: string;
  completeness_pct: number;
  uniqueness_pct: number;
  type_counts: Record<string, number>;
  column_profiles: ColumnProfile[];
  issues: Issue[];
}

export interface ChartSpec {
  type: "bar" | "line" | "scatter" | "histogram" | "none";
  x?: string;
  series?: string[];
  data?: Row[];
  reference_lines?: { y: number; label: string }[];
  highlight_x?: string;
}

export interface AnalysisResult {
  status: "answered" | "unanswerable";
  answer: string;
  question: string;
  intent: string | null;
  mode: "ai" | "manual";
  ai_attempts: number;
  operation: Record<string, unknown>;
  result: { columns: string[]; rows: Row[]; scalar?: { label: string; value: Cell } } | null;
  chart: ChartSpec;
  steps: string[];
  evidence: { columns: string[]; rows: Row[]; total_matching: number; note: string } | null;
  warnings: string[];
  missing?: string[];
  rows_total: number;
}

export interface Suggestion {
  question: string;
  kind: string;
  operation: Record<string, unknown>;
}

export interface Status {
  ai: { configured: boolean; provider: string | null; model: string | null };
  limits: { max_upload_mb: number; max_rows: number; max_columns: number };
  sample_available: boolean;
}

export interface RowsPage { total: number; offset: number; limit: number; columns: string[]; rows: Row[] }

export type InsightKind = "group_change" | "trend" | "period_anomaly" | "group_difference" | "anomaly" | "relationship" | "missing_pattern" | "data_quality";
export type InsightLevel = "strong" | "moderate" | "notable" | "data_quality" | "info";

export interface AnomalyRecord {
  record: string;
  column: string;
  observed: number;
  baseline_median: number;
  limit: number;
  reason: string;
}

export interface Insight {
  id: string;
  kind: InsightKind;
  kind_label: string;
  level: InsightLevel;
  nature: "statistical" | "statistical_anomaly" | "data_quality";
  score: number;
  columns: string[];
  title: string;
  finding: string;
  stats: { label: string; value: Cell }[];
  method: string;
  steps: string[];
  chart: ChartSpec;
  evidence: { columns: string[]; rows: Row[]; total_matching: number; note: string };
  operation: Record<string, unknown> | null;
  caveats: string[];
  anomalies?: AnomalyRecord[];
  context?: Record<string, unknown>;
}

export interface InsightsResponse {
  insights: Insight[];
  candidates_found: number;
  checks: Record<string, number>;
  total_checks: number;
  not_applicable: string[];
  notes: string[];
  rows: number;
  elapsed_ms: number;
}

export interface Explanation { insight_id: string; explanation: string; numbers_checked: boolean; cached: boolean }

export interface FilterSpec { column: string; op: string; value: Cell | Cell[] }

export interface Investigation {
  insight: Insight;
  focus: {
    label: string;
    filters: FilterSpec[];
    baseline_filters: FilterSpec[];
    baseline_label: string;
    metric: string | null;
    drill_columns: string[];
    investigable: boolean;
  };
  follow_ups: { question: string; operation: Record<string, unknown> }[];
}

export interface SegmentComparison {
  segment_rows: number;
  rest_rows: number;
  pool_rows: number;
  metric?: { column: string; segment: Record<string, number | null>; rest: Record<string, number | null> };
  category_differences: { column: string; value: string; segment_share: number; rest_share: number; diff_pts: number }[];
  numeric_differences: { column: string; segment_mean: number; rest_mean: number; segment_median: number; rest_median: number; std_diff: number }[];
  note: string;
}

export interface RowsQuery { total: number; offset: number; limit: number; columns: string[]; rows: (Row & { _row: number })[]; dataset_rows: number }

export interface RecordDetail {
  row: number;
  fields: { column: string; type: string; value: Cell; percentile?: number; median?: number; unusual?: boolean }[];
  exact_copies: number | null;
  note: string;
}

export interface Formula { target: string; kind: string; terms: string[]; fraction?: string; expression: string; holds_share: number; rows_checked: number }

export interface ScenarioOptions {
  targets: string[];
  adjustable: { column: string; affects: string[]; fraction: boolean }[];
  formulas: Formula[];
  group_columns: string[];
  filter_columns: string[];
  available: boolean;
  note: string;
  suggested_exclusion: { target: string; column: string; value: string; effect: number } | null;
}

export interface ScenarioResult {
  kind: "scenario";
  hypothetical: true;
  target: string;
  agg: string;
  label: string;
  baseline: number;
  scenario: number;
  change: number;
  pct_change: number | null;
  summary: string;
  rows_baseline: number;
  rows_scenario: number;
  formula: Formula | null;
  steps: string[];
  assumptions: string[];
  warnings: string[];
  group_by: string | null;
  breakdown: Row[];
  chart: ChartSpec;
}

export interface TrackResult { status: "pass" | "fail" | "error" | "skipped" | "n/a"; actual?: unknown; difference?: number | null; explanation?: string; ms?: number; operation?: Record<string, unknown>; warnings?: string[]; intent?: string }
export interface BenchmarkCase { id: string; category: string; dataset: string; question: string; expected: unknown; expected_kind: string; calculation?: TrackResult; visualization?: TrackResult; interpretation?: TrackResult }
export interface TrackSummary { total: number; pass: number; fail: number; error: number; skipped: number; accuracy: number | null; avg_ms: number | null }
export interface BenchmarkRun {
  suite: string; version: number; generated_by: string; ran_at: string; elapsed_ms: number;
  datasets: Record<string, { path: string; sha256: string; ok: boolean }>;
  tracks: { calculation: TrackSummary; visualization: TrackSummary; interpretation: TrackSummary };
  explanation_quality: string;
  results: BenchmarkCase[];
}
