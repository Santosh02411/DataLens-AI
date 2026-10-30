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

declare global {
  interface Window {
    /** Present only in the self-contained offline demo: responses recorded from the real backend. */
    __DATALENS_DEMO__?: { responses: Record<string, { status: number; body: unknown }>; report?: string };
    /** Present only in the static in-browser build: the real Python backend runs in a Web Worker (Pyodide). */
    __DATALENS_WASM__?: { worker: string };
  }
}

// ---------------------------------------------------------------- in-browser engine (static hosting)

const KEY_STORE = "datalens-gemini-key";
type WasmResp = { status: number; headers: [string, string][]; body: ArrayBuffer | null; error?: string };
let worker: Worker | null = null;
let nextId = 0;
const pending = new Map<number, (r: WasmResp) => void>();

function bootPill(text: string | null, error = false) {
  let el = document.getElementById("dl-boot");
  if (!text) { el?.remove(); return; }
  if (!el) {
    el = document.createElement("div");
    el.id = "dl-boot";
    el.setAttribute("role", "status");
    el.style.cssText = "position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:70;max-width:min(92vw,560px);padding:9px 14px;border-radius:999px;font:13px/1.4 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.3)";
    document.body.appendChild(el);
  }
  el.style.background = error ? "#BE123C" : "rgba(109,40,217,.96)";
  el.style.color = "#fff";
  el.textContent = text;
}

function storedKey(): string {
  try { return localStorage.getItem(KEY_STORE) ?? ""; } catch { return ""; }
}

function getWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(window.__DATALENS_WASM__!.worker);
  worker.onmessage = (e: MessageEvent) => {
    const m = e.data;
    if (m.type === "progress") bootPill(m.text);
    else if (m.type === "ready") bootPill(null);
    else if (m.type === "boot_error") bootPill(`DataLens couldn't start in this browser: ${m.text}`, true);
    else if (m.type === "response") { pending.get(m.id)?.(m); pending.delete(m.id); }
  };
  const key = storedKey();
  const env: Record<string, string> = {
    LLM_PROVIDER: key ? "gemini" : "none", LLM_MODEL: "auto", AI_RATE_PER_MINUTE: "0", AI_DAILY_LIMIT: "0",
    MAX_UPLOAD_MB: "25", MAX_ROWS: "200000", MAX_DATASETS_IN_MEMORY: "3",
  };
  if (key) env.GEMINI_API_KEY = key;
  bootPill("Starting DataLens in your browser… The first visit downloads about 30 MB; later visits are much faster.");
  worker.postMessage({ type: "boot", env });
  return worker;
}

async function wasmCall(method: string, path: string, init?: RequestInit): Promise<WasmResp> {
  const [p, q = ""] = path.split("?");
  let body: ArrayBuffer | null = null;
  const headers: [string, string][] = [];
  if (init?.body instanceof FormData) {
    const req = new Request("http://datalens.local/", { method: "POST", body: init.body });
    body = await req.arrayBuffer();
    headers.push(["content-type", req.headers.get("content-type") ?? "multipart/form-data"]);
  } else if (typeof init?.body === "string") {
    body = new TextEncoder().encode(init.body).buffer as ArrayBuffer;
    headers.push(["content-type", "application/json"]);
  }
  const id = ++nextId;
  const w = getWorker();
  return new Promise((resolve) => {
    pending.set(id, resolve);
    w.postMessage({ type: "request", id, method, path: `/api${p}`, query: q, headers, body }, body ? [body] : []);
  });
}

export const browserEngine = {
  active: () => typeof window !== "undefined" && !!window.__DATALENS_WASM__,
  hasKey: () => !!storedKey(),
  setKey: (key: string | null) => {
    try { key ? localStorage.setItem(KEY_STORE, key.trim()) : localStorage.removeItem(KEY_STORE); } catch { /* storage disabled */ }
    window.location.reload();
  },
  promptForKey: () => {
    const key = window.prompt("Paste your Gemini API key (free at aistudio.google.com/apikey).\nIt's stored only in this browser and sent directly to Google.");
    if (key && key.trim()) browserEngine.setKey(key);
  },
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const demo = typeof window !== "undefined" ? window.__DATALENS_DEMO__ : undefined;
  if (demo) {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${path} ${typeof init?.body === "string" ? init.body : ""}`;
    const hit = demo.responses[key];
    await new Promise((r) => setTimeout(r, 90));
    if (!hit)
      throw new ApiError(0, "offline_demo", "This exact interaction wasn't recorded for the offline demo. Try the suggested options, or run DataLens locally for live calculations on any filter, file or question.");
    if (hit.status >= 400) {
      const e = (hit.body as { error?: { code: string; message: string; details?: string[] } }).error;
      throw new ApiError(hit.status, e?.code ?? "http_error", e?.message ?? `HTTP ${hit.status}`, e?.details ?? []);
    }
    return hit.body as T;
  }
  if (browserEngine.active()) {
    const r = await wasmCall((init?.method ?? "GET").toUpperCase(), path, init);
    if (r.status === 0) throw new ApiError(0, "engine_error", `The in-browser engine hit a problem: ${r.error ?? "unknown error"}`);
    const text = r.body ? new TextDecoder().decode(r.body) : "";
    if (r.status >= 400) {
      let e: { code?: string; message?: string; details?: string[] } | undefined;
      try { e = JSON.parse(text).error; } catch { /* not JSON */ }
      throw new ApiError(r.status, e?.code ?? "http_error", e?.message ?? `HTTP ${r.status}`, e?.details ?? []);
    }
    return JSON.parse(text) as T;
  }
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
  downloadReport: async (id: string) => {
    const r = await wasmCall("GET", `/datasets/${id}/report`);
    if (r.status !== 200 || !r.body) throw new ApiError(r.status, "report_failed", "The report couldn't be generated.");
    const name = /filename="([^"]+)"/.exec(r.headers.find(([k]) => k.toLowerCase() === "content-disposition")?.[1] ?? "")?.[1] ?? "datalens-report.md";
    const url = URL.createObjectURL(new Blob([r.body], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
  reportUrl: (id: string) =>
    window.__DATALENS_DEMO__?.report !== undefined
      ? `data:text/markdown;charset=utf-8,${encodeURIComponent(window.__DATALENS_DEMO__.report)}`
      : `/api/datasets/${id}/report`,
};
