"""Data health profile: every number here is computed directly from the DataFrame."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .ingest import semantic_type
from .utils import fmt_num, jsonable

AMOUNT_HINT = re.compile(r"(price|revenue|amount|sales|cost|qty|quantity|units|total|fee)", re.I)


def build_schema(df: pd.DataFrame) -> dict[str, str]:
    n = len(df)
    return {col: semantic_type(col, df[col], n) for col in df.columns}


MODZ_THRESHOLD = 3.5
MIN_VALUES_FOR_OUTLIERS = 20
MAX_OUTLIER_SHARE = 0.02  # more than this is a genuine cluster or long tail, not isolated anomalies


@dataclass
class RobustBounds:
    """Bounds from the modified z-score (Iglewicz & Hoaglin): |0.6745·(x − median) / MAD| ≥ 3.5.

    Right-skewed, positive columns (amounts, counts) are assessed on a log scale. This single
    definition is used by Data health, the Distribution analysis and Insights, so every screen
    reports the same unusual values.
    """

    lo: float
    hi: float
    scale: str  # "log" or "linear"
    median: float
    n: int

    def mask(self, s: pd.Series) -> pd.Series:
        v = pd.to_numeric(s, errors="coerce")
        out = (v > self.hi) | (((v > 0) & (v < self.lo)) if self.scale == "log" else (v < self.lo))
        return out.fillna(False).astype(bool)

    def describe(self) -> str:
        scale = ", measured on a log scale because the column is strongly right-skewed" if self.scale == "log" else ""
        return f"robust modified z-score ≥ {MODZ_THRESHOLD}{scale}"


def robust_bounds(s: pd.Series) -> RobustBounds | None:
    """None when there's too little data or more than half the values are identical (MAD = 0)."""
    v = pd.to_numeric(s, errors="coerce").dropna().astype(float)
    if len(v) < MIN_VALUES_FOR_OUTLIERS or v.nunique() < 5:
        return None
    positive = v[v > 0]
    skewed = (len(positive) >= MIN_VALUES_FOR_OUTLIERS and positive.skew() > 1
              and (v < 0).mean() < 0.05 and (v == 0).mean() < 0.05)
    x = np.log(positive) if skewed else v
    med = float(x.median())
    mad = float((x - med).abs().median())
    if mad == 0:
        return None
    half = MODZ_THRESHOLD * mad / 0.6745
    if skewed:
        return RobustBounds(math.exp(med - half), math.exp(med + half), "log", float(v.median()), len(v))
    return RobustBounds(med - half, med + half, "linear", float(v.median()), len(v))


def _numeric_stats(s: pd.Series) -> dict[str, Any]:
    v = pd.to_numeric(s, errors="coerce").dropna().astype(float)
    if v.empty:
        return {}
    bounds = robust_bounds(v)
    outliers = int(bounds.mask(v).sum()) if bounds else 0
    return jsonable(
        {
            "mean": v.mean(),
            "std": v.std() if len(v) > 1 else None,
            "min": v.min(),
            "q1": v.quantile(0.25),
            "median": v.median(),
            "q3": v.quantile(0.75),
            "max": v.max(),
            "sum": v.sum(),
            "zeros": int((v == 0).sum()),
            "negatives": int((v < 0).sum()),
            "outliers": outliers,
            "outlier_bounds": [bounds.lo, bounds.hi] if bounds else None,
            "outlier_method": bounds.describe() if bounds else None,
            "skew": v.skew() if len(v) > 2 else None,
        }
    )


def _top_values(s: pd.Series, k: int = 6) -> list[dict[str, Any]]:
    counts = s.dropna().astype(str).value_counts().head(k)
    total = int(s.notna().sum()) or 1
    return [{"value": idx, "count": int(c), "pct": round(100 * c / total, 1)} for idx, c in counts.items()]


def profile_dataframe(df: pd.DataFrame, schema: dict[str, str]) -> dict[str, Any]:
    n_rows, n_cols = df.shape
    total_cells = n_rows * n_cols or 1
    missing_cells = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())

    columns = []
    issues: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        stype = schema[col]
        missing = int(s.isna().sum())
        nunique = int(s.nunique(dropna=True))
        entry: dict[str, Any] = {
            "name": col,
            "type": stype,
            "dtype": str(s.dtype),
            "missing": missing,
            "missing_pct": round(100 * missing / n_rows, 2) if n_rows else 0.0,
            "unique": nunique,
            "unique_pct": round(100 * nunique / max(n_rows - missing, 1), 2),
            "sample_values": [str(jsonable(v)) for v in s.dropna().head(3).tolist()],
        }
        if stype == "numeric":
            entry["stats"] = _numeric_stats(s)
        elif stype == "datetime":
            v = s.dropna()
            if not v.empty:
                entry["stats"] = jsonable(
                    {"min": v.min(), "max": v.max(), "span_days": int((v.max() - v.min()).days)}
                )
        if stype in ("categorical", "text", "boolean", "identifier"):
            entry["top_values"] = _top_values(s)
        columns.append(entry)

        pct = entry["missing_pct"]
        if pct >= 50:
            issues.append(_issue("high", col, f"{col} is mostly empty", f"{fmt_num(missing)} of {fmt_num(n_rows)} values ({pct}%) are missing."))
        elif pct >= 10:
            issues.append(_issue("medium", col, f"{col} has many missing values", f"{fmt_num(missing)} values ({pct}%) are missing."))
        elif missing > 0:
            issues.append(_issue("low", col, f"{col} has missing values", f"{fmt_num(missing)} values ({pct}%) are missing."))
        if n_rows > 1 and nunique <= 1:
            issues.append(_issue("low", col, f"{col} has a single value", "A constant column adds nothing to an analysis."))
        stats = entry.get("stats") or {}
        if stype == "numeric" and stats.get("outliers"):
            lo, hi = stats["outlier_bounds"]
            k = stats["outliers"]
            n_valid = max(n_rows - missing, 1)
            if k / n_valid > MAX_OUTLIER_SHARE:
                issues.append(_issue("low", col, f"{col} has a long tail",
                    f"{fmt_num(k)} values ({100 * k / n_valid:.1f}%) are far from the middle. That many suggests a genuine cluster or long tail rather than isolated errors."))
            else:
                rng = f"{fmt_num(lo)} to {fmt_num(hi)}" if lo > stats["min"] else f"up to {fmt_num(hi)}"
                issues.append(_issue("low", col, f"{col} has unusual values",
                    f"{fmt_num(k)} {'value is' if k == 1 else 'values are'} outside the typical range ({rng}; {stats['outlier_method']}). Unusual doesn't mean wrong."))
        if stype == "numeric" and stats.get("negatives") and AMOUNT_HINT.search(col):
            issues.append(
                _issue(
                    "medium",
                    col,
                    f"{col} has negative values",
                    f"{fmt_num(stats['negatives'])} negative {'value' if stats['negatives'] == 1 else 'values'} in a column that looks like an amount. They may be refunds or entry errors.",
                )
            )

    if duplicate_rows:
        issues.insert(
            0,
            _issue(
                "medium",
                None,
                "Duplicate rows",
                f"{fmt_num(duplicate_rows)} rows are exact copies of another row. They inflate counts and totals.",
            ),
        )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: severity_rank[i["severity"]])

    completeness = 1 - missing_cells / total_cells
    uniqueness = 1 - duplicate_rows / n_rows if n_rows else 1
    score = round(100 * (0.7 * completeness + 0.3 * uniqueness))

    type_counts: dict[str, int] = {}
    for t in schema.values():
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "rows": n_rows,
        "columns": n_cols,
        "missing_cells": missing_cells,
        "missing_pct": round(100 * missing_cells / total_cells, 2),
        "duplicate_rows": duplicate_rows,
        "duplicate_pct": round(100 * duplicate_rows / n_rows, 2) if n_rows else 0.0,
        "quality_score": score,
        "quality_formula": "70% completeness (non-missing cells) + 30% row uniqueness (non-duplicate rows)",
        "completeness_pct": round(100 * completeness, 2),
        "uniqueness_pct": round(100 * uniqueness, 2),
        "type_counts": type_counts,
        "column_profiles": columns,
        "issues": issues,
    }


def _issue(severity: str, column: str | None, title: str, detail: str) -> dict[str, Any]:
    return {"severity": severity, "column": column, "title": title, "detail": detail}


def distribution_counts(s: pd.Series, bins: int = 20) -> list[dict[str, Any]]:
    v = pd.to_numeric(s, errors="coerce").dropna().astype(float)
    if v.empty:
        return []
    counts, edges = np.histogram(v, bins=bins)
    return [
        {"bin_start": float(edges[i]), "bin_end": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]
