import pytest

from app.operations import OperationError, parse_operation, validate_operation


def check(raw, df, schema):
    return validate_operation(parse_operation(raw), df, schema)


def test_schema_types_inferred(sales_schema):
    assert sales_schema["order_id"] == "identifier"
    assert sales_schema["order_date"] == "datetime"
    assert sales_schema["region"] == "categorical"
    assert sales_schema["revenue"] == "numeric"


def test_unknown_operation_type_is_rejected():
    with pytest.raises(OperationError):
        parse_operation({"type": "python", "code": "import os"})


def test_extra_keys_are_rejected():
    with pytest.raises(OperationError):
        parse_operation({"type": "aggregate", "agg": "sum", "column": "revenue", "expr": "df.drop()"})


def test_unknown_column_lists_available(sales_df, sales_schema):
    with pytest.raises(OperationError) as exc:
        check({"type": "aggregate", "agg": "sum", "column": "profit"}, sales_df, sales_schema)
    assert "profit" in exc.value.errors[0] and "revenue" in exc.value.errors[0]


def test_sum_requires_numeric(sales_df, sales_schema):
    with pytest.raises(OperationError) as exc:
        check({"type": "aggregate", "agg": "sum", "column": "region"}, sales_df, sales_schema)
    assert "numeric" in exc.value.errors[0]


def test_column_names_are_canonicalized(sales_df, sales_schema):
    op = check({"type": "aggregate", "agg": "mean", "column": "REVENUE", "group_by": ["Region"]}, sales_df, sales_schema)
    assert op.column == "revenue" and op.group_by == ["region"]


def test_filter_value_must_exist(sales_df, sales_schema):
    with pytest.raises(OperationError) as exc:
        check({"type": "aggregate", "agg": "count", "filters": [{"column": "region", "op": "eq", "value": "Mars"}]}, sales_df, sales_schema)
    assert "Mars" in exc.value.errors[0] and "West" in exc.value.errors[0]


def test_filter_value_case_insensitive(sales_df, sales_schema):
    op = check({"type": "aggregate", "agg": "count", "filters": [{"column": "region", "op": "eq", "value": "west"}]}, sales_df, sales_schema)
    assert op.filters[0].value == "West"


def test_numeric_filter_needs_number(sales_df, sales_schema):
    with pytest.raises(OperationError):
        check({"type": "aggregate", "agg": "count", "filters": [{"column": "units", "op": "gt", "value": "lots"}]}, sales_df, sales_schema)


def test_contains_rejected_on_numeric(sales_df, sales_schema):
    with pytest.raises(OperationError):
        check({"type": "aggregate", "agg": "count", "filters": [{"column": "units", "op": "contains", "value": "1"}]}, sales_df, sales_schema)


def test_period_format_validated(sales_df, sales_schema):
    with pytest.raises(OperationError) as exc:
        check({"type": "period_change", "date_column": "order_date", "value_column": "revenue", "period_a": "spring", "period_b": "2025-Q3"}, sales_df, sales_schema)
    assert "2025-Q3" in exc.value.errors[0]


def test_period_normalized(sales_df, sales_schema):
    op = check({"type": "period_change", "date_column": "order_date", "value_column": "revenue", "period_a": "2025q2", "period_b": "2025-Q3"}, sales_df, sales_schema)
    assert op.period_a == "2025-Q2"


def test_correlation_needs_two_numeric_columns(sales_df, sales_schema):
    with pytest.raises(OperationError):
        check({"type": "correlation", "column_x": "revenue", "column_y": "revenue"}, sales_df, sales_schema)
    with pytest.raises(OperationError):
        check({"type": "correlation", "column_x": "revenue", "column_y": "region"}, sales_df, sales_schema)


def test_limits_enforced():
    with pytest.raises(OperationError):
        parse_operation({"type": "top_rows", "sort_by": "units", "n": 10_000})
