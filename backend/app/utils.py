"""Small helpers shared across modules: JSON-safe conversion and number formatting."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def jsonable(value: Any) -> Any:
    """Convert numpy / pandas scalars and containers into plain JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        ts = pd.Timestamp(value)
        if ts.hour == 0 and ts.minute == 0 and ts.second == 0 and ts.microsecond == 0:
            return ts.strftime("%Y-%m-%d")
        return ts.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if value is pd.NA or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe row dicts."""
    if limit is not None:
        df = df.head(limit)
    cols = [str(c) for c in df.columns]
    out = []
    for row in df.itertuples(index=False, name=None):
        out.append({c: jsonable(v) for c, v in zip(cols, row)})
    return out


def fmt_num(value: Any) -> str:
    """Human-friendly number: thousands separators, at most two decimals."""
    if value is None:
        return "n/a"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(f):
        return "n/a"
    if f.is_integer() and abs(f) < 1e15:
        return f"{int(f):,}"
    if abs(f) >= 100:
        return f"{f:,.2f}"
    if abs(f) >= 1:
        return f"{f:,.2f}".rstrip("0").rstrip(".")
    return f"{f:.4f}".rstrip("0").rstrip(".")


def fmt_pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def fmt_value(value: Any) -> str:
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return fmt_num(value)
    j = jsonable(value)
    return "(missing)" if j is None else str(j)
