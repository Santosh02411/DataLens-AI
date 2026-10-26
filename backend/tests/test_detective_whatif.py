"""Data Detective investigations and the What-If simulator: evidence and calculations checked against pandas."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.investigation import period_bounds
from app.profiling import build_schema
from app.scenarios import ScenarioRequest, detect_formulas, run_scenario

SAMPLE = Path(__file__).resolve().parents[2] / "sample-data" / "retail_sales_2025.csv"


@pytest.fixture
def sample(client):
    ds = client.post("/api/datasets/sample").json()
    raw = pd.read_csv(SAMPLE, parse_dates=["order_date"])
    return client, ds["id"], raw


def orders(n=400, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "region": rng.choice(["N", "S", "E"], n),
        "units": rng.integers(1, 10, n),
        "price": rng.choice([10.0, 25.0, 40.0], n),
        "cost": rng.uniform(1, 5, n).round(2),
        "days": rng.integers(1, 8, n),
    })
    df["revenue"] = df["units"] * df["price"]
    df["profit"] = df["revenue"] - df["cost"]
    return df


# ---------------------------------------------------------------- formulas & scenarios


def test_formula_detection_finds_real_relationships_only():
    df = orders()
    found = {f["target"]: f["expression"] for f in detect_formulas(df, build_schema(df))}
    assert found["revenue"] in ("revenue = units × price", "revenue = price × units")
    assert found["profit"] == "profit = revenue − cost"
    assert "days" not in found


def test_price_increase_scales_revenue_exactly(sample):
    c, ds, raw = sample
    r = c.post(f"/api/datasets/{ds}/scenario", json={"target": "revenue", "adjustments": [{"column": "unit_price", "percent": 5}]}).json()
    assert r["hypothetical"] is True and r["formula"]["expression"] == "revenue = units × unit_price × (1 − discount)"
    assert r["baseline"] == pytest.approx(raw["revenue"].sum())
    assert r["scenario"] == pytest.approx(raw["revenue"].sum() * 1.05)
    assert r["pct_change"] == pytest.approx(5.0)


def test_refunds_stay_negative_under_price_change():
    df = orders(400)
    df.loc[:4, "revenue"] = -df.loc[:4, "revenue"]  # 5 refunds (1.25%) don't follow the formula; it still holds for ≥ 98%
    schema = build_schema(df)
    r = run_scenario(df, schema, ScenarioRequest(target="revenue", adjustments=[{"column": "price", "percent": 10}]))
    assert r["scenario"] == pytest.approx(df["revenue"].sum() * 1.10)


def test_additive_formula_cost_increase_reduces_profit_by_exact_amount():
    df = orders()
    r = run_scenario(df, build_schema(df), ScenarioRequest(target="profit", adjustments=[{"column": "cost", "percent": 10}]))
    assert r["change"] == pytest.approx(-0.10 * df["cost"].sum())


def test_discount_change_is_capped_to_valid_range():
    df = orders()
    df["discount"] = np.random.default_rng(9).choice([0.6, 0.75, 0.9], len(df))
    df["revenue"] = df["units"] * df["price"] * (1 - df["discount"])
    r = run_scenario(df, build_schema(df), ScenarioRequest(target="revenue", adjustments=[{"column": "discount", "percent": 50}]))
    capped = (df["discount"] * 1.5).clip(upper=1.0)  # 0.9 × 1.5 would exceed 100% off; capped at 1.0, never negative revenue
    assert r["scenario"] == pytest.approx((df["units"] * df["price"] * (1 - capped)).sum())
    assert any("capped" in step for step in r["steps"])


def test_exclusion_scenario_matches_pandas(sample):
    c, ds, raw = sample
    r = c.post(f"/api/datasets/{ds}/scenario", json={"target": "shipping_days", "agg": "mean",
               "exclude": [{"column": "channel", "op": "eq", "value": "Partner"}], "group_by": "region"}).json()
    assert r["baseline"] == pytest.approx(raw["shipping_days"].mean())
    assert r["scenario"] == pytest.approx(raw.loc[raw.channel != "Partner", "shipping_days"].mean())
    assert r["rows_scenario"] == int((raw.channel != "Partner").sum())
    west = next(b for b in r["breakdown"] if b["region"] == "West")
    assert west["scenario"] == pytest.approx(raw[(raw.channel != "Partner") & (raw.region == "West")]["shipping_days"].mean())


def test_unrelated_adjustment_is_rejected_not_invented(sample):
    c, ds, _ = sample
    r = c.post(f"/api/datasets/{ds}/scenario", json={"target": "revenue", "adjustments": [{"column": "shipping_days", "percent": 20}]})
    assert r.status_code == 422 and "won't assume" in r.json()["error"]["message"]


@pytest.mark.parametrize("body,fragment", [
    ({"target": "region", "adjustments": [{"column": "units", "percent": 5}]}, "isn't a number column"),
    ({"target": "revenue", "adjustments": [{"column": "region", "percent": 5}]}, "only number columns"),
    ({"target": "revenue"}, "at least one adjustment"),
    ({"target": "revenue", "exclude": [{"column": "units", "op": "gt", "value": 0}]}, "remove every row"),
    ({"target": "revenue", "adjustments": [{"column": "revenue", "percent": 5}, {"column": "units", "percent": 5}]}, "not both"),
])
def test_invalid_scenarios(sample, body, fragment):
    c, ds, _ = sample
    r = c.post(f"/api/datasets/{ds}/scenario", json=body)
    assert r.status_code == 422 and fragment in " ".join(r.json()["error"]["details"])


def test_percent_limits_enforced(sample):
    c, ds, _ = sample
    assert c.post(f"/api/datasets/{ds}/scenario", json={"target": "revenue", "adjustments": [{"column": "unit_price", "percent": 500}]}).status_code == 422


def test_scenario_does_not_modify_data(sample):
    c, ds, raw = sample
    c.post(f"/api/datasets/{ds}/scenario", json={"target": "revenue", "adjustments": [{"column": "unit_price", "percent": 50}]})
    r = c.post(f"/api/datasets/{ds}/run", json={"operation": {"type": "aggregate", "agg": "sum", "column": "revenue"}}).json()
    assert r["result"]["scalar"]["value"] == pytest.approx(raw["revenue"].sum())


# ---------------------------------------------------------------- investigations


def test_period_bounds():
    assert period_bounds("2025-Q3", "quarter") == ("2025-07-01", "2025-09-30")
    assert period_bounds("2024-02", "month") == ("2024-02-01", "2024-02-29")
    assert period_bounds("2025-06-30", "week") == ("2025-06-30", "2025-07-06")


def test_investigation_focus_selects_exactly_the_finding_rows(sample):
    c, ds, raw = sample
    west = next(i for i in c.get(f"/api/datasets/{ds}/insights").json()["insights"] if i["kind"] == "group_change")
    inv = c.get(f"/api/datasets/{ds}/insights/{west['id']}/investigation").json()
    q = raw["order_date"].dt.to_period("Q").astype(str)
    expected = raw[(raw.region == "West") & (q == "2025Q3")]
    rows = c.post(f"/api/datasets/{ds}/rows/query", json={"filters": inv["focus"]["filters"], "limit": 200}).json()
    assert rows["total"] == len(expected)
    assert sum(r["revenue"] or 0 for r in rows["rows"]) == pytest.approx(expected["revenue"].sum())
    seg = c.post(f"/api/datasets/{ds}/segment", json={"filters": inv["focus"]["filters"], "baseline_filters": inv["focus"]["baseline_filters"], "metric": "revenue"}).json()
    assert seg["segment_rows"] == len(expected)
    assert seg["rest_rows"] == int(((q == "2025Q3") & (raw.region != "West")).sum())
    assert seg["metric"]["segment"]["sum"] == pytest.approx(expected["revenue"].sum())


def test_every_follow_up_runs_and_is_allowlisted(sample):
    c, ds, _ = sample
    for ins in c.get(f"/api/datasets/{ds}/insights").json()["insights"]:
        inv = c.get(f"/api/datasets/{ds}/insights/{ins['id']}/investigation").json()
        for fu in inv["follow_ups"]:
            assert fu["operation"]["type"] in {"aggregate", "top_rows", "trend", "period_change", "correlation", "distribution"}
            r = c.post(f"/api/datasets/{ds}/run", json={"operation": fu["operation"], "question": fu["question"]})
            assert r.status_code == 200, (fu["question"], r.text)


def test_anomaly_investigation_isolates_the_flagged_records(sample):
    c, ds, raw = sample
    an = next(i for i in c.get(f"/api/datasets/{ds}/insights").json()["insights"] if i["kind"] == "anomaly")
    inv = c.get(f"/api/datasets/{ds}/insights/{an['id']}/investigation").json()
    rows = c.post(f"/api/datasets/{ds}/rows/query", json={"filters": inv["focus"]["filters"]}).json()
    assert {r["order_id"] for r in rows["rows"]} == set(raw.loc[raw.units >= 40, "order_id"])


def test_segment_requires_filters_and_rejects_bad_ones(sample):
    c, ds, _ = sample
    assert c.post(f"/api/datasets/{ds}/segment", json={"filters": []}).status_code == 422
    r = c.post(f"/api/datasets/{ds}/segment", json={"filters": [{"column": "region", "op": "eq", "value": "Atlantis"}]})
    assert r.status_code == 422 and "Atlantis" in r.json()["error"]["message"]


def test_rows_query_filters_sort_columns_and_record_inspection(sample):
    c, ds, raw = sample
    r = c.post(f"/api/datasets/{ds}/rows/query", json={"filters": [{"column": "region", "op": "eq", "value": "east"}],
               "sort": "revenue", "order": "desc", "limit": 5, "columns": ["order_id", "revenue"]}).json()
    east = raw[raw.region == "East"]
    assert r["total"] == len(east) and r["columns"] == ["order_id", "revenue"]
    assert r["rows"][0]["revenue"] == pytest.approx(east["revenue"].max())
    rec = c.get(f"/api/datasets/{ds}/records/{r['rows'][0]['_row']}").json()
    rev = next(f for f in rec["fields"] if f["column"] == "revenue")
    assert rev["value"] == pytest.approx(east["revenue"].max())
    assert rev["percentile"] == pytest.approx(((raw.revenue.dropna() < rev["value"]).mean() + (raw.revenue.dropna() == rev["value"]).mean() / 2) * 100, abs=0.1)
    assert c.get(f"/api/datasets/{ds}/records/999999").status_code == 404


def test_record_inspection_counts_duplicates_with_missing_values(client):
    csv = b"a,b\n1,\n1,\n2,3\n" + b"".join(f"{i},{i}\n".encode() for i in range(10, 30))
    ds = client.post("/api/datasets", files={"file": ("d.csv", csv, "text/csv")}).json()
    assert client.get(f"/api/datasets/{ds['id']}/records/0").json()["exact_copies"] == 1
