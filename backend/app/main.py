"""DataLens AI API."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote
from typing import Any

import httpx
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm
from .config import Settings, get_settings
from .executor import execute
from .ingest import IngestError, load_dataframe
from .insights import allowed_numbers, discover_insights, unsupported_numbers
from .investigation import build_investigation, compare_segment, inspect_record, query_rows, validate_filters
from .scenarios import ScenarioRequest, run_scenario, scenario_options
from . import benchmark
from .operations import OperationError, parse_operation, validate_operation
from .profiling import build_schema, profile_dataframe
from .report import build_report
from .store import Dataset, DatasetStore
from .suggestions import build_suggestions

log = logging.getLogger("datalens")


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class SegmentBody(BaseModel):
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    baseline_filters: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    metric: str | None = Field(default=None, max_length=200)


class RowsQueryBody(BaseModel):
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    sort: str | None = Field(default=None, max_length=200)
    order: str = Field(default="asc", pattern="^(asc|desc)$")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    search: str | None = Field(default=None, max_length=200)
    columns: list[str] | None = Field(default=None, max_length=200)


class RunBody(BaseModel):
    operation: dict[str, Any]
    question: str | None = Field(default=None, max_length=500)
    record: bool = True  # dashboard tiles pass False so they don't fill the report history


class BenchmarkBody(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=100)
    include_ai: bool = False


def api_error(status: int, code: str, message: str, details: list[str] | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "details": details or []})


def create_app(settings: Settings | None = None, llm_transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="DataLens AI", version="1.0.0")
    app.state.settings = settings
    app.state.store = DatasetStore(settings.max_datasets)
    app.state.interpreter = llm.Interpreter(settings, transport=llm_transport)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail), "details": []}
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()[:5]]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "The request is invalid.", "details": details}})

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Something went wrong on the server. Check the backend logs.", "details": []}})

    store: DatasetStore = app.state.store

    def get_ds(dataset_id: str) -> Dataset:
        ds = store.get(dataset_id)
        if ds is None:
            raise api_error(404, "dataset_not_found", "This dataset is no longer loaded. The server may have restarted. Upload it again.")
        return ds

    def register(df: pd.DataFrame, info, source: str) -> Dataset:
        schema = build_schema(df)
        profile = profile_dataframe(df, schema)
        return store.add(name=info.file_name, df=df, schema=schema, profile=profile, info=info, source=source)

    # ------------------------------------------------------------ routes

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {
            "ai": llm.status(settings),
            "limits": {"max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows, "max_columns": settings.max_columns},
            "sample_available": settings.sample_data_path.exists(),
        }

    @app.post("/api/datasets")
    async def upload(file: UploadFile = File(...), sheet: str | None = Form(default=None)) -> dict[str, Any]:
        limit = settings.max_upload_bytes
        chunks, size = [], 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise api_error(413, "file_too_large", f"The file is larger than {settings.max_upload_mb} MB.")
            chunks.append(chunk)
        try:
            df, info = load_dataframe(file.filename or "dataset", b"".join(chunks), max_rows=settings.max_rows, max_columns=settings.max_columns, sheet=sheet or None)
        except IngestError as exc:
            raise api_error(exc.status, exc.code, exc.message)
        return register(df, info, "upload").summary()

    @app.post("/api/datasets/sample")
    def load_sample() -> dict[str, Any]:
        path = settings.sample_data_path
        if not path.exists():
            raise api_error(404, "sample_missing", "The sample dataset file is missing. Run scripts/generate_sample_data.py.")
        df, info = load_dataframe(path.name, path.read_bytes(), max_rows=settings.max_rows, max_columns=settings.max_columns)
        return register(df, info, "sample").summary()

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str) -> dict[str, Any]:
        return get_ds(dataset_id).summary()

    @app.delete("/api/datasets/{dataset_id}")
    def remove(dataset_id: str) -> dict[str, Any]:
        return {"deleted": store.delete(dataset_id)}

    @app.get("/api/datasets/{dataset_id}/profile")
    def profile(dataset_id: str) -> dict[str, Any]:
        return get_ds(dataset_id).profile

    @app.get("/api/datasets/{dataset_id}/rows")
    def rows(
        dataset_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        sort: str | None = Query(None, max_length=200),
        order: str = Query("asc", pattern="^(asc|desc)$"),
        search: str | None = Query(None, max_length=200),
    ) -> dict[str, Any]:
        from .utils import records

        ds = get_ds(dataset_id)
        df = ds.df
        if search:
            text_cols = [c for c, t in ds.schema.items() if t in ("categorical", "text", "identifier")]
            mask = pd.Series(False, index=df.index)
            for c in text_cols:
                mask |= df[c].astype(str).str.contains(search, case=False, regex=False, na=False)
            df = df.loc[mask]
        if sort:
            if sort not in ds.schema:
                raise api_error(400, "unknown_column", f"There is no column called '{sort}'.")
            df = df.sort_values(sort, ascending=(order == "asc"), na_position="last", kind="stable")
        page = df.iloc[offset : offset + limit]
        return {"total": int(len(df)), "offset": offset, "limit": limit, "columns": list(ds.schema), "rows": records(page)}

    @app.get("/api/datasets/{dataset_id}/suggestions")
    def suggestions(dataset_id: str) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        return {"suggestions": build_suggestions(ds.df, ds.schema)}

    def run_validated(ds: Dataset, op: Any, question: str, intent: str | None, mode: str, attempts: int = 0) -> dict[str, Any]:
        try:
            result = execute(op, ds.df, ds.schema, duplicate_rows=ds.profile["duplicate_rows"])
        except OperationError as exc:
            raise api_error(422, "cannot_compute", exc.errors[0], exc.errors)
        result.update({"question": question, "intent": intent, "mode": mode, "ai_attempts": attempts})
        store.record(ds, {"question": question, "intent": intent, "result": result})
        return result

    @app.post("/api/datasets/{dataset_id}/run")
    def run(dataset_id: str, body: RunBody) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        try:
            op = validate_operation(parse_operation(body.operation), ds.df, ds.schema)
        except OperationError as exc:
            raise api_error(422, "invalid_operation", exc.errors[0], exc.errors)
        question = body.question or "Custom analysis"
        if not body.record:
            try:
                result = execute(op, ds.df, ds.schema, duplicate_rows=ds.profile["duplicate_rows"])
            except OperationError as exc:
                raise api_error(422, "cannot_compute", exc.errors[0], exc.errors)
            result.update({"question": question, "intent": None, "mode": "manual", "ai_attempts": 0})
            return result
        return run_validated(ds, op, question, None, "manual")

    @app.post("/api/datasets/{dataset_id}/ask")
    def ask(dataset_id: str, body: AskBody) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        question = " ".join(body.question.split())
        interpreter: llm.Interpreter = app.state.interpreter
        try:
            intent, op, attempts = interpreter.interpret(question, ds.df, ds.schema)
        except llm.LLMNotConfigured:
            raise api_error(
                503,
                "ai_not_configured",
                "Natural-language questions need an AI provider. Add an API key to backend/.env (see README). "
                "Meanwhile, the suggested questions, the analysis builder and all data health checks work without AI.",
            )
        except llm.LLMError as exc:
            raise api_error(502, "ai_error", str(exc))
        except OperationError as exc:
            raise api_error(
                422,
                "not_understood",
                "The question couldn't be turned into a valid analysis of this dataset. Try naming the columns you mean.",
                exc.errors,
            )
        return run_validated(ds, op, question, intent, "ai", attempts)

    def get_insights(ds: Dataset) -> dict[str, Any]:
        with ds.lock:  # computed once per dataset; concurrent requests wait for the first
            if ds.insights is None:
                ds.insights = discover_insights(ds.df, ds.schema, ds.profile)
            return ds.insights

    @app.get("/api/datasets/{dataset_id}/insights")
    def insights(dataset_id: str) -> dict[str, Any]:
        return get_insights(get_ds(dataset_id))

    @app.post("/api/datasets/{dataset_id}/insights/{insight_id}/explain")
    def explain(dataset_id: str, insight_id: str) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        found = next((i for i in get_insights(ds)["insights"] if i["id"] == insight_id), None)
        if found is None:
            raise api_error(404, "insight_not_found", "That insight isn't available for this dataset.")
        if insight_id in ds.explanations:
            return {"insight_id": insight_id, "explanation": ds.explanations[insight_id], "numbers_checked": True, "cached": True}
        allowed = allowed_numbers(found)
        try:
            text, _ = llm.explain_insight(app.state.interpreter, found, lambda t: unsupported_numbers(t, allowed))
        except llm.LLMNotConfigured:
            raise api_error(503, "ai_not_configured", "AI explanations need an API key in backend/.env. The finding, statistics and evidence above are complete without it.")
        except llm.LLMError as exc:
            raise api_error(502, "ai_error", str(exc))
        ds.explanations[insight_id] = text
        return {"insight_id": insight_id, "explanation": text, "numbers_checked": True, "cached": False}

    @app.get("/api/datasets/{dataset_id}/insights/{insight_id}/investigation")
    def investigation(dataset_id: str, insight_id: str) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        found = next((i for i in get_insights(ds)["insights"] if i["id"] == insight_id), None)
        if found is None:
            raise api_error(404, "insight_not_found", "That insight isn't available for this dataset.")
        if insight_id not in ds.investigations:
            ds.investigations[insight_id] = build_investigation(found, ds.df, ds.schema)
        return {"insight": found, **ds.investigations[insight_id]}

    @app.post("/api/datasets/{dataset_id}/segment")
    def segment(dataset_id: str, body: SegmentBody) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        try:
            filters = validate_filters(body.filters, ds.df, ds.schema)
            baseline = validate_filters(body.baseline_filters, ds.df, ds.schema)
            if not filters:
                raise OperationError(["Add at least one filter to define the segment."])
            metric = body.metric if body.metric in ds.schema else None
            return compare_segment(ds.df, ds.schema, filters, baseline, metric)
        except OperationError as exc:
            raise api_error(422, "invalid_segment", exc.errors[0], exc.errors)

    @app.post("/api/datasets/{dataset_id}/rows/query")
    def rows_query(dataset_id: str, body: RowsQueryBody) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        try:
            filters = validate_filters(body.filters, ds.df, ds.schema)
            return query_rows(ds.df, ds.schema, filters, body.sort, body.order, body.offset, body.limit, body.search, body.columns)
        except OperationError as exc:
            raise api_error(422, "invalid_filters", exc.errors[0], exc.errors)

    @app.get("/api/datasets/{dataset_id}/records/{row}")
    def record(dataset_id: str, row: int) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        try:
            return inspect_record(ds.df, ds.schema, row)
        except OperationError as exc:
            raise api_error(404, "record_not_found", exc.errors[0])

    @app.get("/api/datasets/{dataset_id}/scenario/options")
    def scenario_opts(dataset_id: str) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        with ds.lock:
            opts = scenario_options(ds.df, ds.schema)
        return opts

    @app.post("/api/datasets/{dataset_id}/scenario")
    def scenario(dataset_id: str, body: ScenarioRequest) -> dict[str, Any]:
        ds = get_ds(dataset_id)
        try:
            result = run_scenario(ds.df, ds.schema, body)
        except OperationError as exc:
            raise api_error(422, "unsupported_scenario", exc.errors[0], exc.errors)
        store.record(ds, {"question": f"What if: {result['summary'][:120]}", "intent": None,
                          "result": {"answer": result["summary"], "steps": result["steps"] + ["Assumption: " + a for a in result["assumptions"]],
                                     "warnings": result["warnings"], "result": {"columns": ["case", result["label"]],
                                     "rows": [{"case": "Observed", result["label"]: result["baseline"]}, {"case": "Hypothetical scenario", result["label"]: result["scenario"]}]}}})
        return result

    @app.get("/api/benchmark")
    def benchmark_suite() -> dict[str, Any]:
        suite = benchmark.load_suite()
        return {"suite": suite["suite"], "version": suite["version"], "cases": len(suite["cases"]), "last_run": getattr(app.state, "last_benchmark", None)}

    @app.post("/api/benchmark/run")
    def benchmark_run(body: BenchmarkBody) -> dict[str, Any]:
        result = benchmark.run_suite(app.state.interpreter, include_ai=body.include_ai, ids=body.ids)
        if not body.ids:
            app.state.last_benchmark = result
        return result

    @app.get("/api/datasets/{dataset_id}/report")
    def report(dataset_id: str) -> Response:
        ds = get_ds(dataset_id)
        stem = ds.name.rsplit(".", 1)[0]
        filename = f"{stem}-datalens-report.md"
        ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "datalens-report.md"
        disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
        get_insights(ds)
        return Response(content=build_report(ds), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": disposition})

    # Serve the built frontend (npm run build) from the same server, if present.
    dist = settings.frontend_dist
    if dist.exists() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise api_error(404, "not_found", "Unknown API route.")
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
