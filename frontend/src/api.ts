import type { BenchmarkRun } from "./types";
import type { AnalysisResult, DatasetSummary, Explanation, FilterSpec, InsightsResponse, Investigation, Profile, RecordDetail, RowsPage, RowsQuery, ScenarioOptions, ScenarioResult, SegmentComparison, Status, Suggestion } from "./types";

export class ApiError extends Error {
  code: string;
  details: string[];
  status: number;
  constructor(status: number, code: string, message: string, details: string[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Can't reach the DataLens server. Make sure the backend is running on port 8000.");
  }
  if (!res.ok) {
    let body: { error?: { code: string; message: string; details?: string[] } } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error */
    }
    const e = body.error;
    throw new ApiError(res.status, e?.code ?? "http_error", e?.message ?? `The server returned HTTP ${res.status}.`, e?.details ?? []);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  status: () => request<Status>("/status"),
  upload: (file: File, sheet?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (sheet) form.append("sheet", sheet);
    return request<DatasetSummary>("/datasets", { method: "POST", body: form });
  },
  sample: () => request<DatasetSummary>("/datasets/sample", { method: "POST" }),
  profile: (id: string) => request<Profile>(`/datasets/${id}/profile`),
  suggestions: (id: string) => request<{ suggestions: Suggestion[] }>(`/datasets/${id}/suggestions`),
  rows: (id: string, p: { offset: number; limit: number; sort?: string; order?: "asc" | "desc"; search?: string }) => {
    const q = new URLSearchParams({ offset: String(p.offset), limit: String(p.limit), order: p.order ?? "asc" });
    if (p.sort) q.set("sort", p.sort);
    if (p.search) q.set("search", p.search);
    return request<RowsPage>(`/datasets/${id}/rows?${q}`);
  },
  ask: (id: string, question: string) => request<AnalysisResult>(`/datasets/${id}/ask`, json({ question })),
  run: (id: string, operation: Record<string, unknown>, question?: string, record = true) =>
    request<AnalysisResult>(`/datasets/${id}/run`, json({ operation, question, record })),
  benchmark: () => request<{ suite: string; version: number; cases: number; last_run: BenchmarkRun | null }>(`/benchmark`),
  runBenchmark: (body: { ids?: string[]; include_ai: boolean }) => request<BenchmarkRun>(`/benchmark/run`, json(body)),
  insights: (id: string) => request<InsightsResponse>(`/datasets/${id}/insights`),
  explain: (id: string, insightId: string) =>
    request<Explanation>(`/datasets/${id}/insights/${encodeURIComponent(insightId)}/explain`, { method: "POST" }),
  investigation: (id: string, insightId: string) => request<Investigation>(`/datasets/${id}/insights/${encodeURIComponent(insightId)}/investigation`),
  segment: (id: string, body: { filters: FilterSpec[]; baseline_filters: FilterSpec[]; metric: string | null }) =>
    request<SegmentComparison>(`/datasets/${id}/segment`, json(body)),
  query: (id: string, body: { filters: FilterSpec[]; sort?: string; order?: "asc" | "desc"; offset: number; limit: number; search?: string; columns?: string[] }) =>
    request<RowsQuery>(`/datasets/${id}/rows/query`, json(body)),
  record: (id: string, row: number) => request<RecordDetail>(`/datasets/${id}/records/${row}`),
  scenarioOptions: (id: string) => request<ScenarioOptions>(`/datasets/${id}/scenario/options`),
  scenario: (id: string, body: { target: string; agg: string; adjustments: { column: string; percent: number }[]; exclude: FilterSpec[]; group_by: string | null }) =>
    request<ScenarioResult>(`/datasets/${id}/scenario`, json(body)),
  reportUrl: (id: string) => `/api/datasets/${id}/report`,
};
