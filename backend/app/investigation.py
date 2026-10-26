"""Data Detective: turn a finding into an investigation.

For every insight this module builds:
* a *focus*: the exact, validated filters that select the records behind the finding,
  plus the baseline those records should be compared with;
* *follow-up questions*: allowlisted operations built from the dataset's real columns,
  so they run (and can be verified) without any AI.

It also provides the segment comparison, filtered record exploration and single-record
inspection used by the investigation workspace and the data table. Everything is Pandas;
filters go through the same validator as every other operation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .executor import AGG_LABEL, Result, apply_filters
from .operations import Filter, OperationError, Validator, parse_operation, validate_operation
from .profiling import robust_bounds
from .utils import fmt_num, jsonable, records

MAX_COMPARE_CATEGORIES = 6


# ---------------------------------------------------------------- helpers


def period_bounds(label: str, gran: str) -> tuple[str, str]:
    """First and last day of a period label produced by executor._period_labels."""
    if gran == "quarter":
        year, q = label.split("-Q")
        p = pd.Period(year=int(year), quarter=int(q), freq="Q")
    elif gran == "week":
        start = pd.Timestamp(label)
        return start.strftime("%Y-%m-%d"), (start + pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    elif gran == "year":
        p = pd.Period(label, freq="Y")
    elif gran == "month":
        p = pd.Period(label, freq="M")
    else:
        return label, label
    return p.start_time.strftime("%Y-%m-%d"), p.end_time.strftime("%Y-%m-%d")


def validate_filters(raw: list[dict[str, Any]], df: pd.DataFrame, schema: dict[str, str]) -> list[Filter]:
    if len(raw) > 8:
        raise OperationError(["Use at most 8 filters."])
    try:
        parsed = [Filter(**f) for f in raw]
    except Exception as exc:  # pydantic validation error
        raise OperationError([f"A filter is not in a supported format: {exc}"]) from exc
    v = Validator(df, schema)
    out = v.filters(parsed)
    if v.errors:
        raise OperationError(v.errors)
    return out


def filter_frame(df: pd.DataFrame, filters: list[Filter], schema: dict[str, str], allow_empty: bool = True) -> pd.DataFrame:
    if not filters:
        return df
    try:
        return apply_filters(df, filters, schema, Result(total_rows=len(df)))
    except OperationError:
        if allow_empty:
            return df.iloc[0:0]
        raise


def _metric_label(metric: str | None, agg: str = "sum") -> str:
    return "number of rows" if metric is None else f"{AGG_LABEL.get(agg, agg)} {metric}"


# ---------------------------------------------------------------- focus + follow-ups per finding


def build_investigation(insight: dict[str, Any], df: pd.DataFrame, schema: dict[str, str]) -> dict[str, Any]:
    ctx = insight.get("context") or {}
    kind = insight["kind"]
    cats = [c for c, t in schema.items() if t in ("categorical", "boolean") and 2 <= df[c].nunique() <= 30]
    numeric = [c for c, t in schema.items() if t == "numeric" and df[c].nunique() > 1]
    dates = [c for c, t in schema.items() if t == "datetime"]
    focus: dict[str, Any] = {"label": "", "filters": [], "baseline_filters": [], "baseline_label": "all other rows", "metric": None, "drill_columns": []}
    ups: list[dict[str, Any]] = []

    def other_cats(*exclude: str | None) -> list[str]:
        return [c for c in cats if c not in exclude][:3]

    if kind == "group_change":
        cat, g, metric, a, b, gran, date = ctx["cat"], ctx["group"], ctx["metric"], ctx["period_a"], ctx["period_b"], ctx["gran"], ctx["date"]
        b0, b1 = period_bounds(b, gran)
        a0, a1 = period_bounds(a, gran)
        focus.update(
            label=f"{g} in {b}",
            filters=[{"column": cat, "op": "eq", "value": g}, {"column": date, "op": "between", "value": [b0, b1]}],
            baseline_filters=[{"column": date, "op": "between", "value": [b0, b1]}],
            baseline_label=f"other {cat} groups in {b}",
            metric=metric,
            drill_columns=other_cats(cat),
        )
        finer = "month" if gran in ("quarter", "year") else gran
        ups.append({"question": f"How did {_metric_label(metric)} for {g} move {finer} by {finer}?",
                    "operation": {"type": "trend", "date_column": date, "agg": "sum" if metric else "count", "value_column": metric, "granularity": finer,
                                  "filters": [{"column": cat, "op": "eq", "value": g}]}})
        for c2 in other_cats(cat)[:2]:
            ups.append({"question": f"Within {g}, which {c2} changed most from {a} to {b}?",
                        "operation": {"type": "period_change", "date_column": date, "agg": "sum" if metric else "count", "value_column": metric,
                                      "granularity": gran, "period_a": a, "period_b": b, "group_by": c2, "sort": "asc",
                                      "filters": [{"column": cat, "op": "eq", "value": g}]}})
        ups.append({"question": f"How did every {cat} compare in {b}?",
                    "operation": {"type": "aggregate", "agg": "sum" if metric else "count", "column": metric, "group_by": [cat],
                                  "filters": [{"column": date, "op": "between", "value": [b0, b1]}]}})
        ups.append({"question": f"How did every {cat} compare in {a}?",
                    "operation": {"type": "aggregate", "agg": "sum" if metric else "count", "column": metric, "group_by": [cat],
                                  "filters": [{"column": date, "op": "between", "value": [a0, a1]}]}})
    elif kind == "group_difference":
        cat, g, metric = ctx["cat"], ctx["group"], ctx["metric"]
        focus.update(label=f"{cat} = {g}", filters=[{"column": cat, "op": "eq", "value": g}], baseline_label=f"other {cat} groups",
                     metric=metric, drill_columns=other_cats(cat))
        ups.append({"question": f"How is {metric} spread out for {g}?",
                    "operation": {"type": "distribution", "column": metric, "filters": [{"column": cat, "op": "eq", "value": g}]}})
        for c2 in other_cats(cat)[:2]:
            ups.append({"question": f"Within {g}, which {c2} has the highest average {metric}?",
                        "operation": {"type": "aggregate", "agg": "mean", "column": metric, "group_by": [c2], "filters": [{"column": cat, "op": "eq", "value": g}]}})
        if dates:
            ups.append({"question": f"Has the average {metric} for {g} changed over time?",
                        "operation": {"type": "trend", "date_column": dates[0], "agg": "mean", "value_column": metric, "granularity": "month",
                                      "filters": [{"column": cat, "op": "eq", "value": g}]}})
    elif kind == "anomaly":
        col, hi, lo, side = ctx["column"], ctx["hi"], ctx["lo"], ctx["side"]
        flt = {"column": col, "op": "gt", "value": hi} if side == "high" else {"column": col, "op": "lt", "value": lo}
        focus.update(label=f"unusual {col} values", filters=[flt], baseline_label="typical rows", metric=col, drill_columns=other_cats())
        ups.append({"question": f"Which records have the {'highest' if side == 'high' else 'lowest'} {col}?",
                    "operation": {"type": "top_rows", "sort_by": col, "order": "desc" if side == "high" else "asc", "n": 15}})
        for c2 in other_cats()[:2]:
            ups.append({"question": f"Which {c2} do the unusual {col} values belong to?",
                        "operation": {"type": "aggregate", "agg": "count", "column": None, "group_by": [c2], "filters": [flt]}})
        inside = {"column": col, "op": "lte", "value": hi} if side == "high" else {"column": col, "op": "gte", "value": lo}
        ups.append({"question": f"What does {col} look like without the unusual values?",
                    "operation": {"type": "distribution", "column": col, "filters": [inside]}})
    elif kind in ("trend", "period_anomaly"):
        metric, agg, gran, date = ctx["metric"], ctx["agg"], ctx["gran"], ctx["date"]
        if kind == "period_anomaly":
            p0, p1 = period_bounds(ctx["period"], gran)
            focus.update(label=ctx["period"], filters=[{"column": date, "op": "between", "value": [p0, p1]}],
                         baseline_filters=[{"column": date, "op": "between", "value": [ctx["start"], ctx["end"]]}],
                         baseline_label="the other periods", metric=metric, drill_columns=other_cats())
            for c2 in other_cats()[:2]:
                ups.append({"question": f"Which {c2} drove {ctx['period']}?",
                            "operation": {"type": "aggregate", "agg": agg, "column": metric, "group_by": [c2],
                                          "filters": [{"column": date, "op": "between", "value": [p0, p1]}]}})
        else:
            focus.update(label=f"{ctx['start']} to {ctx['end']}", filters=[{"column": date, "op": "between", "value": [ctx["start"], ctx["end"]]}],
                         baseline_label="rows outside the analysed periods", metric=metric, drill_columns=other_cats())
        for c2 in other_cats()[:2]:
            ups.append({"question": f"How did each {c2} contribute over time?",
                        "operation": {"type": "trend", "date_column": date, "agg": agg, "value_column": metric, "granularity": gran, "group_by": c2,
                                      "filters": [{"column": date, "op": "between", "value": [ctx["start"], ctx["end"]]}]}})
    elif kind == "relationship":
        x, y = ctx["x"], ctx["y"]
        q75 = float(df[x].quantile(0.75))
        focus.update(label=f"top quarter of {x} (≥ {fmt_num(q75)})", filters=[{"column": x, "op": "gte", "value": q75}],
                     baseline_label=f"rows with lower {x}", metric=y, drill_columns=other_cats())
        for c2 in other_cats()[:1]:
            for v in df[c2].dropna().astype(str).value_counts().index[:2]:
                ups.append({"question": f"Does the {x}–{y} relationship hold when {c2} is {v}?",
                            "operation": {"type": "correlation", "column_x": x, "column_y": y, "filters": [{"column": c2, "op": "eq", "value": v}]}})
        ups.append({"question": f"How is {x} spread out?", "operation": {"type": "distribution", "column": x}})
    elif kind == "missing_pattern":
        col, by = ctx["column"], ctx.get("by")
        focus.update(label=f"rows missing {col}", filters=[{"column": col, "op": "is_null"}], baseline_label=f"rows with {col}",
                     metric=None, drill_columns=other_cats(col))
        for c2 in ([by] if by else []) + other_cats(col, by)[:1]:
            ups.append({"question": f"How many rows lack {col} in each {c2}?",
                        "operation": {"type": "aggregate", "agg": "count", "column": None, "group_by": [c2], "filters": [{"column": col, "op": "is_null"}]}})
    elif kind == "data_quality" and ctx.get("negatives"):
        col = ctx["column"]
        focus.update(label=f"negative {col}", filters=[{"column": col, "op": "lt", "value": 0}], baseline_label=f"rows with {col} ≥ 0",
                     metric=col, drill_columns=other_cats())
        for c2 in other_cats()[:2]:
            ups.append({"question": f"Which {c2} do negative {col} values come from?",
                        "operation": {"type": "aggregate", "agg": "count", "column": None, "group_by": [c2], "filters": [{"column": col, "op": "lt", "value": 0}]}})

    # Keep only follow-ups that pass validation against this dataset.
    valid = []
    for u in ups:
        try:
            op = validate_operation(parse_operation(u["operation"]), df, schema)
            valid.append({"question": u["question"], "operation": op.model_dump()})
        except OperationError:
            continue
    try:
        focus["filters"] = [f.model_dump() for f in validate_filters(focus["filters"], df, schema)]
        focus["baseline_filters"] = [f.model_dump() for f in validate_filters(focus["baseline_filters"], df, schema)]
    except OperationError:
        focus["filters"], focus["baseline_filters"] = [], []
    focus["investigable"] = bool(focus["filters"])
    return jsonable({"focus": focus, "follow_ups": valid[:5]})


# ---------------------------------------------------------------- segment vs rest


def compare_segment(df: pd.DataFrame, schema: dict[str, str], filters: list[Filter], baseline: list[Filter], metric: str | None) -> dict[str, Any]:
    pool = filter_frame(df, baseline, schema)
    seg = filter_frame(pool, filters, schema)
    if seg.empty:
        raise OperationError(["No rows match this segment."])
    rest = pool.loc[~pool.index.isin(seg.index)]
    if rest.empty:
        raise OperationError(["Every row in the comparison pool is in the segment, so there's nothing to compare it with."])
    out: dict[str, Any] = {"segment_rows": int(len(seg)), "rest_rows": int(len(rest)), "pool_rows": int(len(pool))}
    if metric and schema.get(metric) == "numeric":
        s, r = seg[metric].dropna().astype(float), rest[metric].dropna().astype(float)
        out["metric"] = {
            "column": metric,
            "segment": {"count": int(len(s)), "sum": jsonable(s.sum()), "mean": jsonable(s.mean() if len(s) else None), "median": jsonable(s.median() if len(s) else None)},
            "rest": {"count": int(len(r)), "sum": jsonable(r.sum()), "mean": jsonable(r.mean() if len(r) else None), "median": jsonable(r.median() if len(r) else None)},
        }
    filter_cols = {f.column for f in filters}
    cat_diffs = []
    for c, t in schema.items():
        if t not in ("categorical", "boolean") or c in filter_cols or not (2 <= df[c].nunique() <= 30):
            continue
        sp = seg[c].astype(str).where(seg[c].notna()).value_counts(normalize=True)
        rp = rest[c].astype(str).where(rest[c].notna()).value_counts(normalize=True)
        for v in sp.index.union(rp.index):
            a, b = float(sp.get(v, 0.0)), float(rp.get(v, 0.0))
            cat_diffs.append({"column": c, "value": v, "segment_share": round(100 * a, 1), "rest_share": round(100 * b, 1), "diff_pts": round(100 * (a - b), 1)})
    cat_diffs.sort(key=lambda d: -abs(d["diff_pts"]))
    seen, top_cats = set(), []
    for d in cat_diffs:  # strongest difference per column first, then fill
        if d["column"] not in seen and abs(d["diff_pts"]) >= 1:
            top_cats.append(d)
            seen.add(d["column"])
    out["category_differences"] = top_cats[:MAX_COMPARE_CATEGORIES]
    num_diffs = []
    for c, t in schema.items():
        if t != "numeric" or c in filter_cols:
            continue
        s, r = seg[c].dropna().astype(float), rest[c].dropna().astype(float)
        if len(s) < 2 or len(r) < 2:
            continue
        pooled = float(np.sqrt((s.var() + r.var()) / 2)) if (s.var() + r.var()) > 0 else 0.0
        if pooled == 0:
            continue
        num_diffs.append({"column": c, "segment_mean": jsonable(s.mean()), "rest_mean": jsonable(r.mean()),
                          "segment_median": jsonable(s.median()), "rest_median": jsonable(r.median()), "std_diff": round(float((s.mean() - r.mean()) / pooled), 2)})
    num_diffs.sort(key=lambda d: -abs(d["std_diff"]))
    out["numeric_differences"] = num_diffs[:6]
    out["note"] = "Descriptive comparison: it shows how the segment differs, not why. Standardized difference = (segment mean − rest mean) ÷ pooled standard deviation."
    return out


# ---------------------------------------------------------------- record exploration + inspection


def query_rows(df: pd.DataFrame, schema: dict[str, str], filters: list[Filter], sort: str | None, order: str,
               offset: int, limit: int, search: str | None, columns: list[str] | None) -> dict[str, Any]:
    d = filter_frame(df, filters, schema)
    if search:
        text_cols = [c for c, t in schema.items() if t in ("categorical", "text", "identifier")]
        mask = pd.Series(False, index=d.index)
        for c in text_cols:
            mask |= d[c].astype(str).str.contains(search, case=False, regex=False, na=False)
        d = d.loc[mask]
    if sort:
        if sort not in schema:
            raise OperationError([f"There is no column called '{sort}'."])
        d = d.sort_values(sort, ascending=(order == "asc"), na_position="last", kind="stable")
    cols = [c for c in (columns or list(schema)) if c in schema] or list(schema)
    page = d.iloc[offset: offset + limit]
    rows = records(page[cols])
    for r, idx in zip(rows, page.index):
        r["_row"] = int(idx)
    return {"total": int(len(d)), "offset": offset, "limit": limit, "columns": cols, "rows": rows, "dataset_rows": int(len(df))}


def inspect_record(df: pd.DataFrame, schema: dict[str, str], row: int) -> dict[str, Any]:
    if row not in df.index:
        raise OperationError([f"Row {row} doesn't exist in this dataset."])
    rec = df.loc[row]
    fields = []
    for c, t in schema.items():
        v = rec[c]
        entry: dict[str, Any] = {"column": c, "type": t, "value": jsonable(v)}
        if t == "numeric" and pd.notna(v):
            col = df[c].dropna().astype(float)
            entry["percentile"] = round(float((col < float(v)).mean() * 100 + (col == float(v)).mean() * 50), 1)
            entry["median"] = jsonable(col.median())
            b = robust_bounds(col)
            entry["unusual"] = bool(b is not None and b.mask(pd.Series([float(v)])).iloc[0])
        fields.append(entry)
    same = (df.eq(rec) | (df.isna() & rec.isna().to_numpy())).all(axis=1)  # missing == missing for this purpose
    duplicates = int(same.sum()) - 1 if len(df) <= 200_000 else None
    return {"row": int(row), "fields": fields, "exact_copies": duplicates,
            "note": "Percentile: share of rows with a lower value (ties count half). Unusual uses the same robust rule as Data health and Insights."}
