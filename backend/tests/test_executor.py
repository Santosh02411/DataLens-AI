import pytest

from app.executor import execute
from app.operations import OperationError, parse_operation, validate_operation


def run(raw, df, schema):
    return execute(validate_operation(parse_operation(raw), df, schema), df, schema)


def test_grouped_sum_matches_pandas(sales_df, sales_schema):
    out = run({"type": "aggregate", "agg": "sum", "column": "revenue", "group_by": ["region"]}, sales_df, sales_schema)
    expected = sales_df.groupby("region")["revenue"].sum()
    got = {r["region"]: r["total revenue"] for r in out["result"]["rows"]}
    assert got == pytest.approx(expected.to_dict())
    assert out["result"]["rows"][0]["region"] == expected.idxmax()
    assert out["status"] == "answered"
    assert out["chart"]["type"] == "bar"


def test_missing_values_are_excluded_and_warned(sales_df, sales_schema):
    out = run({"type": "aggregate", "agg": "mean", "column": "revenue"}, sales_df, sales_schema)
    assert out["result"]["scalar"]["value"] == pytest.approx(sales_df["revenue"].mean())
    assert any("no revenue" in w for w in out["warnings"])
    assert any("Excluded 1 rows" in s for s in out["steps"])


def test_count_rows_with_filter(sales_df, sales_schema):
    out = run({"type": "aggregate", "agg": "count", "filters": [{"column": "region", "op": "eq", "value": "West"}]}, sales_df, sales_schema)
    assert out["result"]["scalar"]["value"] == 12
    assert "12 of 24 rows" in out["steps"][0]


def test_filters_with_no_matches_raise(sales_df, sales_schema):
    with pytest.raises(OperationError):
        run({"type": "aggregate", "agg": "count", "filters": [{"column": "units", "op": "gt", "value": 1000}]}, sales_df, sales_schema)


def test_period_change_finds_biggest_drop(sales_df, sales_schema):
    out = run(
        {"type": "period_change", "date_column": "order_date", "value_column": "revenue", "granularity": "quarter",
         "period_a": "2025-Q2", "period_b": "2025-Q3", "group_by": "region", "sort": "asc"},
        sales_df, sales_schema,
    )
    top = out["result"]["rows"][0]
    assert top["region"] == "West"
    assert top["2025-Q2"] == pytest.approx(600.0)
    assert top["2025-Q3"] == pytest.approx(240.0)
    assert top["change"] == pytest.approx(-360.0)
    assert "West had the biggest drop" in out["answer"]


def test_period_change_missing_period_is_honest(sales_df, sales_schema):
    with pytest.raises(OperationError) as exc:
        run({"type": "period_change", "date_column": "order_date", "value_column": "revenue", "period_a": "2025-Q3", "period_b": "2025-Q4"}, sales_df, sales_schema)
    assert "No rows fall in 2025-Q4" in exc.value.errors[0]


def test_trend_by_month(sales_df, sales_schema):
    out = run({"type": "trend", "date_column": "order_date", "value_column": "revenue", "granularity": "month"}, sales_df, sales_schema)
    rows = {r["period"]: r["total revenue"] for r in out["result"]["rows"]}
    expected = sales_df.groupby(sales_df["order_date"].dt.to_period("M").astype(str))["revenue"].sum()
    assert rows == pytest.approx(expected.to_dict())
    assert out["chart"]["type"] == "line"


def test_correlation_value_and_caveat(sales_df, sales_schema):
    out = run({"type": "correlation", "column_x": "units", "column_y": "rating"}, sales_df, sales_schema)
    expected = sales_df["units"].corr(sales_df["rating"])
    assert out["result"]["scalar"]["value"] == pytest.approx(round(expected, 4))
    assert any("not that one causes" in w for w in out["warnings"])
    assert any("Only 24 rows" in w for w in out["warnings"])


def test_top_rows(sales_df, sales_schema):
    out = run({"type": "top_rows", "sort_by": "units", "n": 3}, sales_df, sales_schema)
    assert [r["units"] for r in out["result"]["rows"]] == [24, 23, 22]


def test_distribution_categorical(sales_df, sales_schema):
    out = run({"type": "distribution", "column": "region"}, sales_df, sales_schema)
    counts = {r["region"]: r["count"] for r in out["result"]["rows"]}
    assert counts == {"West": 12, "East": 12}


def test_unanswerable_passthrough(sales_df, sales_schema):
    out = run({"type": "unanswerable", "reason": "No profit column.", "missing": ["profit"]}, sales_df, sales_schema)
    assert out["status"] == "unanswerable" and out["result"] is None


def test_evidence_rows_come_from_data(sales_df, sales_schema):
    out = run({"type": "aggregate", "agg": "sum", "column": "revenue", "group_by": ["region"]}, sales_df, sales_schema)
    ids = {r["order_id"] for r in out["evidence"]["rows"]}
    top_region = out["result"]["rows"][0]["region"]
    assert ids <= set(sales_df.loc[sales_df["region"] == top_region, "order_id"])
