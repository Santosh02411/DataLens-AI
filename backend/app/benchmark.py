"""Accuracy benchmark: runs a fixed suite of questions through the normal analysis pipeline and
compares the results with independently computed expected answers (benchmarks/suite_v1.json).

Tracks are reported separately:
* calculation   - the stored operation, validated and executed exactly as /run does (deterministic)
* visualization - the chart drawn for a result shows the same numbers as the result table (deterministic)
* interpretation- the question text alone, sent through the AI interpreter (/ask path); needs an API key
Explanation quality is subjective and is not scored automatically.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import pandas as pd

from .config import BACKEND_DIR, REPO_DIR
from .executor import execute
from .ingest import load_dataframe
from .operations import OperationError, parse_operation, validate_operation
from .profiling import build_schema
from .utils import jsonable

SUITE_PATH = BACKEND_DIR / "benchmarks" / "suite_v1.json"


def load_suite() -> dict[str, Any]:
    return json.loads(SUITE_PATH.read_text())


def _load_datasets(suite: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for name, meta in suite["datasets"].items():
        path = REPO_DIR / meta["path"]
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != meta["sha256"]:
            out[name] = {"error": f"Dataset '{name}' doesn't match the benchmark version (sha256 {digest[:12]}… ≠ {meta['sha256'][:12]}…)."}
            continue
        df, _ = load_dataframe(path.name, data, max_rows=1_000_000, max_columns=500)
        schema = build_schema(df)
        out[name] = {"df": df, "schema": schema, "dups": int(df.duplicated().sum())}
    return out


def _extract(result: dict[str, Any], spec: dict[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "status":
        return result.get("status")
    rows = (result.get("result") or {}).get("rows") or []
    if kind == "scalar":
        return ((result.get("result") or {}).get("scalar") or {}).get("value")
    if kind == "first":
        return rows[0].get(spec["column"]) if rows else None
    if kind == "cell":
        for r in rows:
            if all(str(r.get(k)) == str(v) for k, v in spec["match"].items()):
                return r.get(spec["column"])
        return None
    if kind == "table":
        return {str(r.get(spec["key"])): r.get(spec["column"]) for r in rows}
    if kind == "column_list":
        return [r.get(spec["column"]) for r in rows]
    return None


def _close(a: Any, b: float, rel: float, ab: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= ab + rel * abs(float(b))
    except (TypeError, ValueError):
        return False


def _compare(actual: Any, exp: dict[str, Any]) -> tuple[bool, Any, str]:
    kind, want = exp["kind"], exp["value"]
    if kind == "number":
        if actual is None:
            return False, None, "No numeric result was produced."
        diff = float(actual) - float(want)
        ok = _close(actual, want, exp.get("rel_tol", 1e-9), exp.get("abs_tol", 1e-6))
        return ok, diff, "" if ok else f"Off by {diff:+.6g} (tolerance ±{exp.get('abs_tol', 1e-6)} + {exp.get('rel_tol', 1e-9)}×expected)."
    if kind == "table":
        if not isinstance(actual, dict):
            return False, None, "No table was produced."
        missing = [k for k in want if k not in actual]
        extra = [k for k in actual if k not in want]
        wrong = {k: actual[k] - v for k, v in want.items() if k in actual and not _close(actual[k], v, exp.get("rel_tol", 1e-9), exp.get("abs_tol", 1e-6))}
        ok = not missing and not extra and not wrong
        why = "; ".join(filter(None, [f"missing groups {missing}" if missing else "", f"unexpected groups {extra}" if extra else "",
                                      f"wrong values {wrong}" if wrong else ""]))
        return ok, (max((abs(v) for v in wrong.values()), default=0.0) if not missing and not extra else None), why
    if kind in ("text", "status"):
        ok = str(actual) == str(want)
        return ok, None, "" if ok else f"Got '{actual}', expected '{want}'."
    if kind == "list":
        ok = list(actual or []) == list(want)
        return ok, None, "" if ok else f"Got {actual}, expected {want}."
    return False, None, f"Unknown expectation kind '{kind}'."


def _chart_consistent(result: dict[str, Any]) -> bool | None:
    chart = result.get("chart") or {}
    rows = (result.get("result") or {}).get("rows") or []
    if chart.get("type") in (None, "none", "scatter") or not chart.get("data") or not rows:  # scatter plots raw points, not the result table
        return None
    table_values = {round(float(v), 6) for r in rows for v in r.values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for d in chart["data"]:
        for s in chart.get("series") or []:
            v = d.get(s)
            if isinstance(v, (int, float)) and round(float(v), 6) not in table_values:
                return False
    return True


def run_case(case: dict[str, Any], data: dict[str, Any], interpreter: Any = None, include_ai: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"id": case["id"], "category": case["category"], "dataset": case["dataset"], "question": case["question"],
                           "expected": case["expected"]["value"], "expected_kind": case["expected"]["kind"]}
    ds = data[case["dataset"]]
    if "error" in ds:
        out.update(calculation={"status": "error", "explanation": ds["error"]})
        return jsonable(out)

    # ---- calculation track
    if case.get("operation") is not None:
        t0 = time.perf_counter()
        calc: dict[str, Any] = {"operation": case["operation"]}
        try:
            op = validate_operation(parse_operation(case["operation"]), ds["df"], ds["schema"])
            res = execute(op, ds["df"], ds["schema"], duplicate_rows=ds["dups"])
            calc["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if case["expected"]["kind"] == "error_contains":
                calc.update(status="fail", actual=res.get("answer"), explanation="Expected the request to be refused, but it was answered.")
            else:
                actual = _extract(res, case["extract"])
                ok, diff, why = _compare(actual, case["expected"])
                want_warn = case.get("expect_warning")
                if ok and want_warn and not any(want_warn in w for w in res.get("warnings", [])):
                    ok, why = False, f"The number is right but the warning '{want_warn}' was missing."
                calc.update(status="pass" if ok else "fail", actual=actual, difference=diff, explanation=why or "Matches the expected answer.",
                            warnings=res.get("warnings", []))
                viz = _chart_consistent(res)
                out["visualization"] = {"status": "n/a" if viz is None else "pass" if viz else "fail"}
        except OperationError as exc:
            calc["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            msg = " ".join(exc.errors)
            if case["expected"]["kind"] == "error_contains":
                ok = case["expected"]["value"] in msg
                calc.update(status="pass" if ok else "fail", actual=msg, explanation="Correctly refused." if ok else f"Refused, but with a different reason: {msg}")
            else:
                calc.update(status="error", actual=msg, explanation=f"The pipeline raised an error: {msg}")
        except Exception as exc:  # noqa: BLE001 - a crash is recorded as an execution error
            calc.update(status="error", ms=round((time.perf_counter() - t0) * 1000, 1), explanation=f"Unexpected {type(exc).__name__}.")
        out["calculation"] = calc

    # ---- interpretation track (AI)
    if case.get("ai"):
        if not include_ai or interpreter is None or not interpreter.configured:
            out["interpretation"] = {"status": "skipped", "explanation": "AI not configured or not requested."}
        else:
            t0 = time.perf_counter()
            try:
                intent, op, _ = interpreter.interpret(case["question"], ds["df"], ds["schema"])
                res = execute(op, ds["df"], ds["schema"], duplicate_rows=ds["dups"])
                if case["expected"]["kind"] == "status":
                    actual = res.get("status")
                    ok, why = actual == case["expected"]["value"], ""
                else:
                    actual = _extract(res, case["extract"])
                    ok, _, why = _compare(actual, case["expected"])
                out["interpretation"] = {"status": "pass" if ok else "fail", "actual": actual, "intent": intent, "operation": op.model_dump(),
                                         "explanation": why or "The AI chose an operation that produces the expected answer.",
                                         "ms": round((time.perf_counter() - t0) * 1000, 1)}
            except Exception as exc:  # noqa: BLE001
                out["interpretation"] = {"status": "error", "explanation": str(exc)[:300], "ms": round((time.perf_counter() - t0) * 1000, 1)}
    return jsonable(out)


def run_suite(interpreter: Any = None, include_ai: bool = False, ids: list[str] | None = None) -> dict[str, Any]:
    suite = load_suite()
    data = _load_datasets(suite)
    t0 = time.perf_counter()
    cases = [c for c in suite["cases"] if not ids or c["id"] in ids]
    results = [run_case(c, data, interpreter, include_ai) for c in cases]

    def track(name: str) -> dict[str, Any]:
        rs = [r[name] for r in results if name in r]
        counts = {s: sum(1 for r in rs if r["status"] == s) for s in ("pass", "fail", "error", "skipped", "n/a")}
        scored = counts["pass"] + counts["fail"] + counts["error"]
        times = [r["ms"] for r in rs if "ms" in r]
        return {"total": len(rs), **counts, "accuracy": round(100 * counts["pass"] / scored, 1) if scored else None,
                "avg_ms": round(sum(times) / len(times), 1) if times else None}

    return {
        "suite": suite["suite"], "version": suite["version"], "generated_by": suite["generated_by"],
        "datasets": {k: {"path": v["path"], "sha256": v["sha256"], "ok": "error" not in data[k]} for k, v in suite["datasets"].items()},
        "ran_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "tracks": {"calculation": track("calculation"), "visualization": track("visualization"), "interpretation": track("interpretation")},
        "explanation_quality": "Not scored automatically: explanation quality is subjective.",
        "results": results,
    }
