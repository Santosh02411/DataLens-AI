"""Execute a validated operation with Pandas and build an explainable result.

Every number in a result comes from this module. The answer sentence, the
method steps, the evidence rows and the warnings are generated
deterministically from the computation, never by the language model.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .operations import (
    AggregateOp,
    CorrelationOp,
    DistributionOp,
    Filter,
    OperationError,
    PeriodChangeOp,
    TopRowsOp,
    TrendOp,
    UnanswerableOp,
)
from .profiling import MAX_OUTLIER_SHARE, robust_bounds
from .stats import spearman
from .utils import fmt_num, fmt_pct, fmt_value, jsonable, records

EVIDENCE_ROWS = 15
SMALL_GROUP = 5
AGG_LABEL = {
    "count": "count",
    "sum": "total",
    "mean": "average",
    "median": "median",
    "min": "minimum",
    "max": "maximum",
    "nunique": "number of distinct values",
}
OP_WORDS = {
    "eq": "is",
    "ne": "is not",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "in": "is one of",
    "not_in": "is not one of",
    "contains": "contains",
    "between": "is between",
    "is_null": "is missing",
    "not_null": "is present",
}
FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}


class Result:
    def __init__(self, total_rows: int):
        self.total_rows = total_rows
        self.steps: list[str] = []
        self.warnings: list[str] = []

    def step(self, text: str) -> None:
        self.steps.append(text)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)


# ---------------------------------------------------------------- filters


def _describe_value(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(fmt_value(x) for x in v)
    return fmt_value(v)


def _filter_mask(df: pd.DataFrame, f: Filter, stype: str) -> pd.Series:
    s = df[f.column]
    if stype == "datetime" and f.op not in ("is_null", "not_null"):
        conv = lambda x: pd.Timestamp(x)  # noqa: E731
    elif stype == "numeric":
        conv = float
    else:
        conv = lambda x: x  # noqa: E731
    op, val = f.op, f.value
    if op == "eq":
        return s == conv(val)
    if op == "ne":
        return (s != conv(val)) & s.notna()
    if op == "gt":
        return s > conv(val)
    if op == "gte":
        return s >= conv(val)
    if op == "lt":
        return s < conv(val)
    if op == "lte":
        return s <= conv(val)
    if op == "between":
        lo, hi = conv(val[0]), conv(val[1])
        if lo > hi:
            lo, hi = hi, lo
        return (s >= lo) & (s <= hi)
    if op == "in":
        return s.isin([conv(x) for x in val])
    if op == "not_in":
        return ~s.isin([conv(x) for x in val]) & s.notna()
    if op == "contains":
        return s.astype(str).str.contains(str(val), case=False, regex=False) & s.notna()
    if op == "is_null":
        return s.isna()
    if op == "not_null":
        return s.notna()
    raise OperationError([f"Unsupported filter '{op}'."])


def apply_filters(df: pd.DataFrame, filters: list[Filter], schema: dict[str, str], res: Result) -> pd.DataFrame:
    out = df
    for f in filters:
        mask = _filter_mask(out, f, schema[f.column]).fillna(False).astype(bool)
        out = out.loc[mask]
        value = "" if f.op in ("is_null", "not_null") else f" {_describe_value(f.value)}"
        res.step(f"Kept rows where {f.column} {OP_WORDS[f.op]}{value}: {fmt_num(len(out))} of {fmt_num(res.total_rows)} rows remain.")
    if filters and out.empty:
        raise OperationError(["No rows match these filters, so there is nothing to calculate."])
    return out


def _drop_missing(d: pd.DataFrame, column: str | None, res: Result, reason: str = "") -> pd.DataFrame:
    if column is None:
        return d
    missing = int(d[column].isna().sum())
    if missing:
        pct = 100 * missing / max(len(d), 1)
        res.step(f"Excluded {fmt_num(missing)} rows where {column} is missing{reason}.")
        res.warn(f"{fmt_num(missing)} rows ({pct:.1f}%) have no {column} and were left out of this result.")
        if pct >= 20:
            res.warn(f"More than a fifth of {column} is missing, so treat this result with caution.")
        return d.loc[d[column].notna()]
    return d


def _agg(series: pd.Series | None, agg: str, frame: pd.DataFrame) -> Any:
    if agg == "count":
        return int(len(frame)) if series is None else int(series.notna().sum())
    if agg == "nunique":
        return int(series.nunique(dropna=True))
    return getattr(series, agg)()


def _metric_label(agg: str, column: str | None) -> str:
    if agg == "count" and column is None:
        return "rows"
    return f"{AGG_LABEL[agg]} {column}"


def _group_label(row: pd.Series | tuple, keys: list[str]) -> str:
    vals = row if isinstance(row, tuple) else tuple(row[k] for k in keys)
    return " / ".join(fmt_value(v) for v in vals)


def _evidence(d: pd.DataFrame, note: str, sort_col: str | None = None, ascending: bool = False) -> dict[str, Any]:
    frame = d
    if sort_col and sort_col in d.columns and (pd.api.types.is_numeric_dtype(d[sort_col]) or pd.api.types.is_datetime64_any_dtype(d[sort_col])):
        frame = d.sort_values(sort_col, ascending=ascending, na_position="last")
    return {
        "columns": [str(c) for c in d.columns],
        "rows": records(frame, EVIDENCE_ROWS),
        "total_matching": int(len(d)),
        "note": note,
    }


# ---------------------------------------------------------------- operations


def _run_aggregate(op: AggregateOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    col = op.column
    if op.agg != "count" or col is not None:
        d = _drop_missing(d, col, res)
    if d.empty:
        raise OperationError(["No rows are left to calculate on after removing missing values."])
    label = _metric_label(op.agg, col)

    if not op.group_by:
        value = _agg(d[col] if col else None, op.agg, d)
        res.step(f"Calculated the {label} over {fmt_num(len(d))} rows.")
        scope = " matching the filters" if op.filters else ""
        if op.agg == "count" and col is None:
            answer = f"There are {fmt_num(value)} rows{scope}."
        else:
            answer = f"The {label} is {fmt_num(value) if not isinstance(value, pd.Timestamp) else fmt_value(value)} across {fmt_num(len(d))} rows{scope}."
        return {
            "answer": answer,
            "result": {"columns": ["metric", "value"], "rows": [{"metric": label, "value": jsonable(value)}], "scalar": {"label": label, "value": jsonable(value)}},
            "chart": {"type": "none"},
            "evidence": _evidence(d, f"Rows used in the calculation ({fmt_num(len(d))} total)", col),
        }

    keys = op.group_by
    for k in keys:
        missing = int(d[k].isna().sum())
        if missing:
            res.step(f"Excluded {fmt_num(missing)} rows with no {k}.")
            res.warn(f"{fmt_num(missing)} rows have no {k} and aren't part of any group.")
            d = d.loc[d[k].notna()]
    grouped = d.groupby(keys, sort=False, observed=True)
    if op.agg == "count" and col is None:
        values = grouped.size()
    elif op.agg == "count":
        values = grouped[col].count()
    elif op.agg == "nunique":
        values = grouped[col].nunique()
    else:
        values = grouped[col].agg(op.agg)
    sizes = grouped.size()
    table = pd.DataFrame({"value": values, "rows": sizes}).reset_index()
    table = table.sort_values("value", ascending=(op.sort == "asc"), kind="stable")
    n_groups = len(table)
    res.step(f"Grouped by {' and '.join(keys)} into {fmt_num(n_groups)} groups and calculated the {label} for each.")
    res.step(f"Sorted groups by {label}, {'lowest' if op.sort == 'asc' else 'highest'} first.")
    small = int((table["rows"] < SMALL_GROUP).sum())
    if small:
        res.warn(f"{small} group(s) have fewer than {SMALL_GROUP} rows, so their {AGG_LABEL[op.agg]} may not be reliable.")
    shown = table.head(op.limit)
    if n_groups > op.limit:
        res.step(f"Showing the first {op.limit} of {fmt_num(n_groups)} groups.")

    label_col = " / ".join(keys)
    shown = shown.assign(**{label_col: [_group_label(tuple(r), keys) for r in shown[keys].itertuples(index=False, name=None)]})
    top = shown.iloc[0]
    word = "lowest" if op.sort == "asc" else "highest"
    answer = f"{top[label_col]} has the {word} {label} ({fmt_value(top['value'])})"
    if len(shown) > 1:
        nxt = shown.iloc[1]
        answer += f", followed by {nxt[label_col]} ({fmt_value(nxt['value'])})"
    answer += "."
    top_mask = np.ones(len(d), dtype=bool)
    for k in keys:
        top_mask &= (d[k] == top[k]).to_numpy()
    out_rows = [{label_col: r[label_col], label: jsonable(r["value"]), "rows": int(r["rows"])} for _, r in shown.iterrows()]
    return {
        "answer": answer,
        "result": {"columns": [label_col, label, "rows"], "rows": out_rows},
        "chart": {"type": "bar", "x": label_col, "series": [label], "data": [{label_col: r[label_col], label: r[label]} for r in out_rows]}
        if all(isinstance(r[label], (int, float)) for r in out_rows)
        else {"type": "none"},
        "evidence": _evidence(d.loc[top_mask], f"Rows behind the top group, {top[label_col]} ({fmt_num(int(top_mask.sum()))} rows)", col),
    }


def _run_top_rows(op: TopRowsOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    d = _drop_missing(d, op.sort_by, res)
    if d.empty:
        raise OperationError([f"No rows have a value for {op.sort_by}."])
    ordered = d.sort_values(op.sort_by, ascending=(op.order == "asc"), kind="stable").head(op.n)
    res.step(f"Sorted {fmt_num(len(d))} rows by {op.sort_by}, {'smallest' if op.order == 'asc' else 'largest'} first, and kept the top {len(ordered)}.")
    cols = op.columns or [c for c in df.columns][:10]
    if op.sort_by not in cols:
        cols = [op.sort_by] + cols
    ordered_view = ordered[cols]
    label_col = next((c for c in df.columns if schema[c] == "identifier"), None) or next(
        (c for c in df.columns if schema[c] in ("categorical", "text")), None
    )
    first = ordered.iloc[0]
    lead = f" ({label_col} {fmt_value(first[label_col])})" if label_col else ""
    word = "smallest" if op.order == "asc" else "largest"
    answer = f"The {word} {op.sort_by} value is {fmt_value(first[op.sort_by])}{lead}. Showing the top {len(ordered)} rows."
    chart_data = []
    for i, (_, r) in enumerate(ordered.iterrows()):
        x = fmt_value(r[label_col]) if label_col else f"Row {i + 1}"
        chart_data.append({"label": x, op.sort_by: jsonable(r[op.sort_by])})
    chart = {"type": "bar", "x": "label", "series": [op.sort_by], "data": chart_data} if schema[op.sort_by] == "numeric" else {"type": "none"}
    return {
        "answer": answer,
        "result": {"columns": [str(c) for c in cols], "rows": records(ordered_view)},
        "chart": chart,
        "evidence": {"columns": [str(c) for c in d.columns], "rows": records(ordered, EVIDENCE_ROWS), "total_matching": int(len(d)), "note": "These are the rows themselves."},
    }


def _period_labels(dates: pd.Series, granularity: str) -> pd.Series:
    """Label each date with its period ("2025-07", "2025-Q3", "2025", week start "2025-06-30").

    Labels are computed once per distinct day and mapped back, which keeps this fast on large files.
    """
    days = dates.dt.normalize()
    uniq = pd.DatetimeIndex(days.dropna().unique())
    if granularity == "quarter":
        labels = uniq.year.astype(str) + "-Q" + uniq.quarter.astype(str)
    elif granularity == "week":
        labels = (uniq - pd.to_timedelta(uniq.weekday, unit="D")).strftime("%Y-%m-%d")
    elif granularity == "year":
        labels = uniq.year.astype(str)
    elif granularity == "month":
        labels = uniq.strftime("%Y-%m")
    else:
        labels = uniq.strftime("%Y-%m-%d")
    return days.map(dict(zip(uniq, labels)))


def _partial_periods(dates: pd.Series, granularity: str) -> tuple[str | None, str | None]:
    """Labels of the first/last period when the data doesn't cover it fully, else None."""
    if granularity == "day" or dates.empty:
        return None, None
    freq = FREQ[granularity]
    first, last = dates.min(), dates.max()
    p_first, p_last = first.to_period(freq), last.to_period(freq)
    first_label = last_label = None
    if first.date() > p_first.start_time.date():
        first_label = _period_labels(pd.Series([first]), granularity).iloc[0]
    if last.date() < p_last.end_time.date():
        last_label = _period_labels(pd.Series([last]), granularity).iloc[0]
    return first_label, last_label


def _partial_period_warnings(dates: pd.Series, granularity: str, res: Result, agg: str, only: set[str] | None = None) -> None:
    first_label, last_label = _partial_periods(dates, granularity)
    effect = f"its {AGG_LABEL[agg]} will look lower than a full {granularity}" if agg in ("count", "sum", "nunique") else "it is based on partial data"
    if last_label and (only is None or last_label in only):
        res.warn(f"The data ends on {dates.max():%Y-%m-%d}, so {last_label} is incomplete and {effect}.")
    if first_label and (only is None or first_label in only):
        res.warn(f"The data starts on {dates.min():%Y-%m-%d}, so {first_label} is incomplete and {effect}.")


def _value_series(d: pd.DataFrame, op: Any, keys: list[str]) -> pd.Series:
    col = op.value_column
    g = d.groupby(keys, sort=True, observed=True)
    if op.agg == "count" and col is None:
        return g.size()
    if op.agg == "count":
        return g[col].count()
    if op.agg == "nunique":
        return g[col].nunique()
    return g[col].agg(op.agg)


def _run_trend(op: TrendOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    d = _drop_missing(d, op.date_column, res)
    if op.value_column:
        d = _drop_missing(d, op.value_column, res)
    if d.empty:
        raise OperationError(["No rows with dates are left to chart."])
    d = d.assign(_period=_period_labels(d[op.date_column], op.granularity))
    label = _metric_label(op.agg, op.value_column)
    res.step(f"Assigned each row to a {op.granularity} using {op.date_column}.")
    _partial_period_warnings(d[op.date_column], op.granularity, res, op.agg)

    if op.group_by:
        d = _drop_missing(d, op.group_by, res)
        totals = d.groupby(op.group_by, observed=True).size().sort_values(ascending=False)
        top_groups = list(totals.index[:6])
        if len(totals) > 6:
            res.step(f"Kept the 6 largest {op.group_by} groups by row count (of {len(totals)}).")
        d = d.loc[d[op.group_by].isin(top_groups)]
        series = _value_series(d, op, ["_period", op.group_by])
        wide = series.unstack(op.group_by).sort_index()
        res.step(f"Calculated the {label} for each {op.granularity} and {op.group_by}.")
        names = [fmt_value(g) for g in wide.columns]
        wide.columns = names
        data = [{"period": idx, **{n: jsonable(row[n]) for n in names}} for idx, row in wide.iterrows()]
        totals_by_group = wide.sum(numeric_only=True)
        lead = totals_by_group.idxmax()
        answer = f"Across {len(wide)} {op.granularity}s, {lead} leads on {label}. The chart shows each {op.group_by} over time."
        result_rows = data
        result_cols = ["period"] + names
        chart = {"type": "line", "x": "period", "series": names, "data": data}
        peak_period = wide.sum(axis=1).idxmax()
    else:
        series = _value_series(d, op, ["_period"]).sort_index()
        res.step(f"Calculated the {label} for each of {len(series)} {op.granularity}s.")
        data = [{"period": idx, label: jsonable(v)} for idx, v in series.items()]
        first_p, last_p = series.index[0], series.index[-1]
        first_v, last_v = series.iloc[0], series.iloc[-1]
        change = (last_v - first_v) / abs(first_v) * 100 if first_v not in (0, None) and not pd.isna(first_v) else None
        peak_period = series.idxmax()
        low_period = series.idxmin()
        answer = (
            f"The {label} went from {fmt_num(first_v)} in {first_p} to {fmt_num(last_v)} in {last_p}"
            f"{f' ({fmt_pct(change)})' if change is not None else ''}. "
            f"Peak: {peak_period} ({fmt_num(series.max())}); low: {low_period} ({fmt_num(series.min())})."
        )
        result_rows = data
        result_cols = ["period", label]
        chart = {"type": "line", "x": "period", "series": [label], "data": data}
    if len(data) < 3:
        res.warn(f"Only {len(data)} {op.granularity}(s) of data, which is too few to call it a trend.")
    ev = d.loc[d["_period"] == peak_period].drop(columns="_period")
    return {
        "answer": answer,
        "result": {"columns": result_cols, "rows": result_rows},
        "chart": chart,
        "evidence": _evidence(ev, f"Rows from the peak {op.granularity}, {peak_period} ({fmt_num(len(ev))} rows)", op.value_column),
    }


def _run_period_change(op: PeriodChangeOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    d = _drop_missing(d, op.date_column, res)
    if op.value_column:
        d = _drop_missing(d, op.value_column, res)
    d = d.assign(_period=_period_labels(d[op.date_column], op.granularity))
    available = sorted(d["_period"].unique())
    for p in (op.period_a, op.period_b):
        if p not in available:
            span = f"{available[0]} to {available[-1]}" if available else "no dates"
            raise OperationError([f"No rows fall in {p}. The data covers {span}."])
    res.step(f"Assigned each row to a {op.granularity} using {op.date_column}, then kept {op.period_a} and {op.period_b}.")
    d2 = d.loc[d["_period"].isin([op.period_a, op.period_b])]
    in_a, in_b = d2["_period"] == op.period_a, d2["_period"] == op.period_b
    _partial_period_warnings(df[op.date_column].dropna(), op.granularity, res, op.agg, only={op.period_a, op.period_b})
    label = _metric_label(op.agg, op.value_column)

    if not op.group_by:
        series = _value_series(d2, op, ["_period"])
        va, vb = series.get(op.period_a), series.get(op.period_b)
        change = vb - va
        pct = change / abs(va) * 100 if va else None
        res.step(f"Calculated the {label} in each period and the difference.")
        direction = "rose" if change > 0 else "fell" if change < 0 else "was unchanged"
        answer = f"The {label} {direction} from {fmt_num(va)} in {op.period_a} to {fmt_num(vb)} in {op.period_b}"
        answer += f" ({fmt_num(change)}, {fmt_pct(pct)})." if change else "."
        row = {"period_a": jsonable(va), "period_b": jsonable(vb), "change": jsonable(change), "pct_change": jsonable(pct)}
        return {
            "answer": answer,
            "result": {"columns": [op.period_a, op.period_b, "change", "% change"], "rows": [{op.period_a: row["period_a"], op.period_b: row["period_b"], "change": row["change"], "% change": row["pct_change"]}]},
            "chart": {"type": "bar", "x": "period", "series": [label], "data": [{"period": op.period_a, label: row["period_a"]}, {"period": op.period_b, label: row["period_b"]}]},
            "evidence": _evidence(d2.loc[in_b].drop(columns="_period"), f"Rows from {op.period_b} ({fmt_num(int(in_b.sum()))} rows)", op.value_column),
        }

    g = op.group_by
    d2 = _drop_missing(d2, g, res)
    series = _value_series(d2, op, ["_period", g]).unstack("_period")
    sizes = d2.groupby(["_period", g], observed=True).size().unstack("_period")
    for p in (op.period_a, op.period_b):
        if p not in series.columns:
            series[p] = np.nan
            sizes[p] = 0
    table = pd.DataFrame({
        "a": series[op.period_a],
        "b": series[op.period_b],
        "n_a": sizes[op.period_a].fillna(0).astype(int),
        "n_b": sizes[op.period_b].fillna(0).astype(int),
    })
    if op.agg in ("count", "sum"):
        table[["a", "b"]] = table[["a", "b"]].fillna(0)
    table["change"] = table["b"] - table["a"]
    table["pct"] = np.where(table["a"].abs() > 0, table["change"] / table["a"].abs() * 100, np.nan)
    table = table.dropna(subset=["change"]).sort_values("change", ascending=(op.sort == "asc"), kind="stable")
    if table.empty:
        raise OperationError([f"No {g} has data in both {op.period_a} and {op.period_b}."])
    res.step(f"Calculated the {label} for each {g} in both periods, then the change from {op.period_a} to {op.period_b}.")
    res.step(f"Sorted by change, {'biggest drop' if op.sort == 'asc' else 'biggest gain'} first.")
    small = int(((table["n_a"] < SMALL_GROUP) | (table["n_b"] < SMALL_GROUP)).sum())
    if small:
        res.warn(f"{small} {g} group(s) have fewer than {SMALL_GROUP} rows in one of the periods, so their change is less reliable.")
    shown = table.head(op.limit)
    top_name = shown.index[0]
    top = shown.iloc[0]
    if op.sort == "asc":
        if top["change"] < 0:
            answer = f"{fmt_value(top_name)} had the biggest drop in {label}: {fmt_num(top['a'])} in {op.period_a} to {fmt_num(top['b'])} in {op.period_b} ({fmt_num(top['change'])}, {fmt_pct(None if pd.isna(top['pct']) else top['pct'])})."
        else:
            answer = f"No {g} decreased. The smallest change was {fmt_value(top_name)} ({fmt_num(top['change'])}, {fmt_pct(None if pd.isna(top['pct']) else top['pct'])})."
    else:
        if top["change"] > 0:
            answer = f"{fmt_value(top_name)} had the biggest gain in {label}: {fmt_num(top['a'])} in {op.period_a} to {fmt_num(top['b'])} in {op.period_b} (+{fmt_num(top['change'])}, {fmt_pct(None if pd.isna(top['pct']) else top['pct'])})."
        else:
            answer = f"No {g} increased. The best result was {fmt_value(top_name)} ({fmt_num(top['change'])})."
    decreased = int((table["change"] < 0).sum())
    answer += f" {decreased} of {len(table)} {g} groups decreased."
    rows = [
        {g: fmt_value(idx), op.period_a: jsonable(r["a"]), op.period_b: jsonable(r["b"]), "change": jsonable(r["change"]), "% change": jsonable(r["pct"])}
        for idx, r in shown.iterrows()
    ]
    chart = {"type": "bar", "x": g, "series": [op.period_a, op.period_b], "data": [{g: r[g], op.period_a: r[op.period_a], op.period_b: r[op.period_b]} for r in rows]}
    ev = d2.loc[(d2[g] == top_name) & (d2["_period"] == op.period_b)].drop(columns="_period")
    return {
        "answer": answer,
        "result": {"columns": [g, op.period_a, op.period_b, "change", "% change"], "rows": rows},
        "chart": chart,
        "evidence": _evidence(ev, f"{fmt_value(top_name)} rows in {op.period_b} ({fmt_num(len(ev))} rows)", op.value_column),
    }


def _strength(r: float) -> str:
    a = abs(r)
    if a < 0.1:
        return "no meaningful"
    if a < 0.3:
        return "a weak"
    if a < 0.5:
        return "a moderate"
    return "a strong"


def _run_correlation(op: CorrelationOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    before = len(d)
    d = d.loc[d[op.column_x].notna() & d[op.column_y].notna()]
    dropped = before - len(d)
    if dropped:
        res.step(f"Excluded {fmt_num(dropped)} rows missing {op.column_x} or {op.column_y}.")
        res.warn(f"{fmt_num(dropped)} rows were left out because one of the two values is missing.")
    n = len(d)
    if n < 3:
        raise OperationError([f"Only {n} rows have both {op.column_x} and {op.column_y}; at least 3 are needed."])
    x, y = d[op.column_x].astype(float), d[op.column_y].astype(float)
    if x.nunique() < 2 or y.nunique() < 2:
        raise OperationError(["One of the columns has the same value in every row, so a correlation can't be measured."])
    r = float(x.corr(y)) if op.method == "pearson" else spearman(x, y)
    name = "Pearson" if op.method == "pearson" else "Spearman rank"
    res.step(f"Calculated the {name} correlation between {op.column_x} and {op.column_y} over {fmt_num(n)} rows.")
    ci = None
    if n > 3 and abs(r) < 1:
        z, se = math.atanh(r), 1 / math.sqrt(n - 3)
        ci = (math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se))
        res.step(f"Estimated a 95% confidence interval with the Fisher z method: {ci[0]:.2f} to {ci[1]:.2f}.")
        if ci[0] < 0 < ci[1]:
            res.warn("The confidence interval includes zero, so the data doesn't rule out no relationship at all.")
    if n < 30:
        res.warn(f"Only {n} rows, so this correlation estimate is unstable.")
    res.warn("Correlation shows that two values move together, not that one causes the other.")
    direction = "" if abs(r) < 0.1 else (" positive" if r > 0 else " negative")
    meaning = ""
    if abs(r) >= 0.1:
        meaning = f" As {op.column_x} goes up, {op.column_y} tends to go {'up' if r > 0 else 'down'}."
    answer = f"There is {_strength(r)}{direction} relationship between {op.column_x} and {op.column_y} (r = {r:.2f}, n = {fmt_num(n)}).{meaning}"
    sample = d.sample(n=min(600, n), random_state=7) if n > 600 else d
    if n > 600:
        res.step("Plotted a random sample of 600 points; the correlation uses all rows.")
    return {
        "answer": answer,
        "result": {
            "columns": ["measure", "value"],
            "rows": [
                {"measure": f"{name} r", "value": round(r, 4)},
                {"measure": "rows used", "value": n},
                {"measure": "95% CI low", "value": round(ci[0], 4) if ci else None},
                {"measure": "95% CI high", "value": round(ci[1], 4) if ci else None},
            ],
            "scalar": {"label": f"{name} r", "value": round(r, 4)},
        },
        "chart": {"type": "scatter", "x": op.column_x, "series": [op.column_y], "data": records(sample[[op.column_x, op.column_y]])},
        "evidence": _evidence(d, f"Rows with both values ({fmt_num(n)} total), highest {op.column_x} first", op.column_x),
    }


def _run_distribution(op: DistributionOp, df: pd.DataFrame, schema: dict[str, str], res: Result) -> dict[str, Any]:
    d = apply_filters(df, op.filters, schema, res)
    d = _drop_missing(d, op.column, res)
    if d.empty:
        raise OperationError([f"{op.column} has no values to describe."])
    stype = schema[op.column]
    s = d[op.column]
    if stype == "numeric":
        v = s.astype(float)
        counts, edges = np.histogram(v, bins=op.bins)
        res.step(f"Split {fmt_num(len(v))} values of {op.column} into {op.bins} equal-width bins and counted each.")
        bounds = robust_bounds(v)
        flagged = d.loc[bounds.mask(v)] if bounds else d.iloc[0:0]
        if bounds:
            res.step(f"Flagged values outside {fmt_num(bounds.lo)} to {fmt_num(bounds.hi)} as unusual ({bounds.describe()}).")
        cluster = bool(bounds) and len(flagged) / len(v) > MAX_OUTLIER_SHARE
        outliers = d.iloc[0:0] if cluster else flagged
        if cluster:
            res.warn(f"{fmt_num(len(flagged))} values ({100 * len(flagged) / len(v):.1f}%) sit far from the middle, which looks like a long tail or cluster rather than isolated anomalies.")
        elif len(outliers):
            res.warn(f"{fmt_num(len(outliers))} unusual values could pull the average away from the typical value. Unusual doesn't mean wrong.")
        mean, median = v.mean(), v.median()
        answer = (
            f"{op.column} ranges from {fmt_num(v.min())} to {fmt_num(v.max())}. "
            f"The median is {fmt_num(median)} and the average is {fmt_num(mean)}"
            f"{' (the average is pulled up by large values)' if mean > median * 1.15 and median > 0 else ''}."
        )
        if len(outliers):
            answer += f" {fmt_num(len(outliers))} values are unusually far from the rest."
        data = [{"bin": f"{fmt_num(edges[i])}–{fmt_num(edges[i + 1])}", "count": int(counts[i])} for i in range(len(counts))]
        ev = _evidence(outliers, f"Unusual values ({fmt_num(len(outliers))} rows)", op.column) if len(outliers) else _evidence(d, "Sample of rows", op.column)
        return {
            "answer": answer,
            "result": {"columns": ["bin", "count"], "rows": data},
            "chart": {"type": "histogram", "x": "bin", "series": ["count"], "data": data},
            "evidence": ev,
        }
    if stype == "datetime":
        labels = _period_labels(s, "month")
        counts = labels.value_counts().sort_index()
        res.step(f"Counted rows per month of {op.column}.")
        data = [{"month": k, "count": int(v)} for k, v in counts.items()]
        answer = f"{op.column} runs from {s.min():%Y-%m-%d} to {s.max():%Y-%m-%d}. The busiest month is {counts.idxmax()} with {fmt_num(counts.max())} rows."
        return {
            "answer": answer,
            "result": {"columns": ["month", "count"], "rows": data},
            "chart": {"type": "bar", "x": "month", "series": ["count"], "data": data},
            "evidence": _evidence(d, "Sample of rows", op.column),
        }
    counts = s.astype(str).value_counts()
    total = int(counts.sum())
    res.step(f"Counted how often each of the {fmt_num(len(counts))} distinct values of {op.column} appears.")
    top = counts.head(20)
    data = [{op.column: k, "count": int(v), "share": round(100 * v / total, 1)} for k, v in top.items()]
    if len(counts) > 20:
        other = int(counts.iloc[20:].sum())
        res.step(f"Grouped the remaining {len(counts) - 20} values as Other ({fmt_num(other)} rows).")
        data.append({op.column: "Other", "count": other, "share": round(100 * other / total, 1)})
    lead = top.index[0]
    answer = f"The most common {op.column} is {lead} ({fmt_num(top.iloc[0])} rows, {100 * top.iloc[0] / total:.1f}%), out of {fmt_num(len(counts))} distinct values."
    return {
        "answer": answer,
        "result": {"columns": [op.column, "count", "share"], "rows": data},
        "chart": {"type": "bar", "x": op.column, "series": ["count"], "data": [{op.column: r[op.column], "count": r["count"]} for r in data]},
        "evidence": _evidence(d.loc[s.astype(str) == lead], f"Rows where {op.column} is {lead}"),
    }


RUNNERS = {
    AggregateOp: _run_aggregate,
    TopRowsOp: _run_top_rows,
    TrendOp: _run_trend,
    PeriodChangeOp: _run_period_change,
    CorrelationOp: _run_correlation,
    DistributionOp: _run_distribution,
}


def execute(op: Any, df: pd.DataFrame, schema: dict[str, str], duplicate_rows: int | None = None) -> dict[str, Any]:
    """Run a *validated* operation. Returns an explainable, JSON-safe result.

    `duplicate_rows` lets callers that already know the dataset's duplicate count skip recomputing it.
    """
    if isinstance(op, UnanswerableOp):
        return {
            "status": "unanswerable",
            "answer": op.reason,
            "missing": op.missing,
            "operation": op.model_dump(),
            "result": None,
            "chart": {"type": "none"},
            "steps": ["Checked the question against the dataset's columns and values."],
            "evidence": None,
            "warnings": [],
            "rows_total": int(len(df)),
        }
    res = Result(total_rows=len(df))
    runner = RUNNERS[type(op)]
    out = runner(op, df, schema, res)
    dups = int(df.duplicated().sum()) if duplicate_rows is None else duplicate_rows
    if dups:
        res.warn(f"The dataset has {fmt_num(dups)} duplicate rows, and they are included in this calculation.")
    return jsonable(
        {
            "status": "answered",
            "answer": out["answer"],
            "operation": op.model_dump(),
            "result": out["result"],
            "chart": out["chart"],
            "steps": res.steps,
            "evidence": out["evidence"],
            "warnings": res.warnings,
            "rows_total": int(len(df)),
        }
    )
