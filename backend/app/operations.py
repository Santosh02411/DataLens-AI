"""The allowlist of analytical operations DataLens can run.

The LLM (or the manual query builder) can only produce one of these JSON shapes.
Each is parsed by Pydantic, then checked against the real dataset schema:
column names must exist, types must fit the operation, and filter values must
exist in the data. Nothing is ever evaluated as code.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

AggName = Literal["count", "sum", "mean", "median", "min", "max", "nunique"]
Granularity = Literal["day", "week", "month", "quarter", "year"]
FilterOpName = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "between", "is_null", "not_null"]

NUMERIC_AGGS = {"sum", "mean", "median"}
ORDERED_AGGS = {"min", "max"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filter(Strict):
    column: str = Field(max_length=200)
    op: FilterOpName
    value: Any = None


class AggregateOp(Strict):
    type: Literal["aggregate"]
    agg: AggName
    column: str | None = None
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    sort: Literal["desc", "asc"] = "desc"
    limit: int = Field(15, ge=1, le=100)


class TopRowsOp(Strict):
    type: Literal["top_rows"]
    sort_by: str
    order: Literal["desc", "asc"] = "desc"
    n: int = Field(10, ge=1, le=100)
    columns: list[str] = Field(default_factory=list, max_length=12)
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class TrendOp(Strict):
    type: Literal["trend"]
    date_column: str
    agg: AggName = "sum"
    value_column: str | None = None
    granularity: Granularity = "month"
    group_by: str | None = None
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class PeriodChangeOp(Strict):
    type: Literal["period_change"]
    date_column: str
    agg: AggName = "sum"
    value_column: str | None = None
    granularity: Literal["month", "quarter", "year"] = "quarter"
    period_a: str
    period_b: str
    group_by: str | None = None
    sort: Literal["asc", "desc"] = "asc"
    limit: int = Field(15, ge=1, le=100)
    filters: list[Filter] = Field(default_factory=list, max_length=6)

    @field_validator("period_a", "period_b")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip().upper().replace(" ", "")


class CorrelationOp(Strict):
    type: Literal["correlation"]
    column_x: str
    column_y: str
    method: Literal["pearson", "spearman"] = "pearson"
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class DistributionOp(Strict):
    type: Literal["distribution"]
    column: str
    bins: int = Field(20, ge=5, le=50)
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class UnanswerableOp(Strict):
    type: Literal["unanswerable"]
    reason: str = Field(max_length=600)
    missing: list[str] = Field(default_factory=list, max_length=10)


Operation = Annotated[
    Union[AggregateOp, TopRowsOp, TrendOp, PeriodChangeOp, CorrelationOp, DistributionOp, UnanswerableOp],
    Field(discriminator="type"),
]
OPERATION_ADAPTER: TypeAdapter[Any] = TypeAdapter(Operation)


class OperationError(Exception):
    """The operation can't run against this dataset. `errors` are user-readable."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_operation(raw: Any) -> Any:
    try:
        return OPERATION_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors()[:6]:
            loc = ".".join(str(p) for p in err["loc"])
            msgs.append(f"{loc}: {err['msg']}" if loc else err["msg"])
        raise OperationError(msgs or ["The operation is not in a supported format."]) from exc


# ---------------------------------------------------------------- validation against the dataset


PERIOD_PATTERNS = {
    "month": re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$"),
    "quarter": re.compile(r"^(\d{4})-?Q([1-4])$"),
    "year": re.compile(r"^(\d{4})$"),
}


def normalize_period(label: str, granularity: str) -> str | None:
    m = PERIOD_PATTERNS[granularity].match(label)
    if not m:
        return None
    if granularity == "quarter":
        return f"{m.group(1)}-Q{m.group(2)}"
    return label


class Validator:
    def __init__(self, df: pd.DataFrame, schema: dict[str, str]):
        self.df = df
        self.schema = schema
        self.lookup = {c.lower(): c for c in schema}
        self.errors: list[str] = []

    # -- helpers
    def col(self, name: str | None, role: str, allowed: set[str] | None = None) -> str | None:
        if name is None:
            self.errors.append(f"{role} is required.")
            return None
        actual = self.lookup.get(name.strip().lower())
        if actual is None:
            available = ", ".join(list(self.schema)[:25])
            self.errors.append(f"There is no column called '{name}'. Available columns: {available}.")
            return None
        if allowed and self.schema[actual] not in allowed:
            nice = " or ".join(sorted(allowed))
            self.errors.append(f"{role} '{actual}' is {self.schema[actual]}, but this needs a {nice} column.")
        return actual

    def check_agg(self, agg: str, column: str | None, role: str = "Value column") -> str | None:
        if agg == "count" and column is None:
            return None
        if agg in NUMERIC_AGGS:
            return self.col(column, role, {"numeric"})
        if agg in ORDERED_AGGS:
            return self.col(column, role, {"numeric", "datetime"})
        return self.col(column, role)

    def _known_value(self, column: str, value: Any) -> Any:
        series = self.df[column].dropna()
        values = {str(v).lower(): v for v in series.unique()[:20000]}
        hit = values.get(str(value).strip().lower())
        if hit is None:
            sample = ", ".join(map(str, list(series.astype(str).value_counts().index[:12])))
            self.errors.append(f"'{value}' doesn't appear in {column}. Values include: {sample}.")
            return value
        return hit

    def _coerce_scalar(self, column: str, value: Any, stype: str) -> Any:
        if stype == "numeric":
            try:
                return float(value)
            except (TypeError, ValueError):
                self.errors.append(f"Filter on {column} needs a number, got '{value}'.")
                return value
        if stype == "datetime":
            ts = pd.to_datetime(str(value), errors="coerce")
            if pd.isna(ts):
                self.errors.append(f"Filter on {column} needs a date like 2025-07-01, got '{value}'.")
                return value
            return ts.strftime("%Y-%m-%d")
        if stype == "boolean":
            if str(value).lower() in ("true", "yes", "1"):
                return True
            if str(value).lower() in ("false", "no", "0"):
                return False
            self.errors.append(f"Filter on {column} needs true or false.")
            return value
        return self._known_value(column, value)

    def filters(self, filters: list[Filter]) -> list[Filter]:
        out = []
        for f in filters:
            col = self.col(f.column, "Filter column")
            if col is None:
                continue
            stype = self.schema[col]
            value = f.value
            if f.op in ("is_null", "not_null"):
                value = None
            elif f.op in ("gt", "gte", "lt", "lte"):
                if stype not in ("numeric", "datetime"):
                    self.errors.append(f"'{f.op}' needs a number or date column; {col} is {stype}.")
                else:
                    value = self._coerce_scalar(col, value, stype)
            elif f.op == "between":
                if stype not in ("numeric", "datetime") or not isinstance(value, list) or len(value) != 2:
                    self.errors.append(f"'between' on {col} needs a number or date column and two values [low, high].")
                else:
                    value = [self._coerce_scalar(col, v, stype) for v in value]
            elif f.op in ("in", "not_in"):
                if not isinstance(value, list) or not value or len(value) > 50:
                    self.errors.append(f"'{f.op}' on {col} needs a list of 1 to 50 values.")
                else:
                    value = [self._coerce_scalar(col, v, stype) for v in value]
            elif f.op == "contains":
                if stype in ("numeric", "datetime", "boolean"):
                    self.errors.append(f"'contains' only works on text columns; {col} is {stype}.")
                elif not isinstance(value, str) or not value.strip():
                    self.errors.append(f"'contains' on {col} needs some text to search for.")
            else:  # eq, ne
                if isinstance(value, (list, dict)) or value is None:
                    self.errors.append(f"'{f.op}' on {col} needs a single value.")
                else:
                    value = self._coerce_scalar(col, value, stype)
            out.append(Filter(column=col, op=f.op, value=value))
        return out


def validate_operation(op: Any, df: pd.DataFrame, schema: dict[str, str]) -> Any:
    """Return a normalized copy of `op` with canonical column names, or raise OperationError."""
    if isinstance(op, UnanswerableOp):
        return op
    v = Validator(df, schema)
    data = op.model_dump()
    if hasattr(op, "filters"):
        data["filters"] = [f.model_dump() for f in v.filters(op.filters)]

    if isinstance(op, AggregateOp):
        if op.agg != "count" and op.column is None:
            v.errors.append(f"'{op.agg}' needs a column to aggregate.")
        else:
            data["column"] = v.check_agg(op.agg, op.column)
        data["group_by"] = [v.col(g, "Group-by column") for g in op.group_by]
        if len(set(data["group_by"])) != len(data["group_by"]):
            v.errors.append("Group-by columns must be different.")
    elif isinstance(op, TopRowsOp):
        data["sort_by"] = v.col(op.sort_by, "Sort column", {"numeric", "datetime"})
        data["columns"] = [v.col(c, "Column") for c in op.columns]
    elif isinstance(op, TrendOp):
        data["date_column"] = v.col(op.date_column, "Date column", {"datetime"})
        data["value_column"] = v.check_agg(op.agg, op.value_column)
        if op.agg != "count" and op.value_column is None:
            v.errors.append(f"'{op.agg}' over time needs a value column.")
        if op.group_by:
            data["group_by"] = v.col(op.group_by, "Group-by column")
    elif isinstance(op, PeriodChangeOp):
        data["date_column"] = v.col(op.date_column, "Date column", {"datetime"})
        data["value_column"] = v.check_agg(op.agg, op.value_column)
        if op.agg != "count" and op.value_column is None:
            v.errors.append(f"'{op.agg}' needs a value column.")
        for key in ("period_a", "period_b"):
            norm = normalize_period(getattr(op, key), op.granularity)
            if norm is None:
                example = {"month": "2025-07", "quarter": "2025-Q3", "year": "2025"}[op.granularity]
                v.errors.append(f"{key} '{getattr(op, key)}' isn't a valid {op.granularity}; use a format like {example}.")
            else:
                data[key] = norm
        if data["period_a"] == data["period_b"]:
            v.errors.append("The two periods must be different.")
        if op.group_by:
            data["group_by"] = v.col(op.group_by, "Group-by column")
    elif isinstance(op, CorrelationOp):
        data["column_x"] = v.col(op.column_x, "First column", {"numeric"})
        data["column_y"] = v.col(op.column_y, "Second column", {"numeric"})
        if data["column_x"] and data["column_x"] == data["column_y"]:
            v.errors.append("Pick two different columns to correlate.")
    elif isinstance(op, DistributionOp):
        data["column"] = v.col(op.column, "Column")

    if v.errors:
        raise OperationError(v.errors)
    return parse_operation(data)
