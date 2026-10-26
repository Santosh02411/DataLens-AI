"""Build backend/benchmarks/suite_v1.json: the accuracy benchmark's cases and expected answers.

Expected values are computed here with plain pandas on the raw CSV files. This deliberately does
NOT import any DataLens code (no app.ingest / app.executor), so the benchmark checks the app
against an independent calculation. The edge-case dataset's answers were also worked out by hand;
the HAND dict below must agree with pandas or this script stops.

Run from the repository root:  python scripts/compute_benchmark_expectations.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RETAIL = ROOT / "sample-data" / "retail_sales_2025.csv"
EDGE = ROOT / "backend" / "benchmarks" / "edge_cases_v1.csv"
OUT = ROOT / "backend" / "benchmarks" / "suite_v1.json"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def r(x: float, nd: int = 6) -> float:
    return round(float(x), nd)


def main() -> None:
    d = pd.read_csv(RETAIL, parse_dates=["order_date"])
    e = pd.read_csv(EDGE, parse_dates=["date"])

    # Hand-computed answers for the 10-row edge dataset (see the CSV): verified against pandas below.
    HAND = {
        "sum_amount": 1420.5,          # 100 + 250.5 + 80 - 20 + 400 + 400 + 150 + 60 (2 blanks skipped)
        "mean_amount": 177.5625,       # 1420.5 / 8 non-missing values
        "median_amount": 125.0,        # sorted: -20, 60, 80, 100 | 150, 250.5, 400, 400 -> (100 + 150) / 2
        "missing_amount": 2,
        "rows": 10,                    # includes one exact duplicate (id 6)
        "city_sum": {"Belagavi": 780.0, "Pune": 410.5, "Mysuru": 230.0},
        "qty_ge_2": 6,                 # ids 2, 3, 6, 6, 8, 9
        "feb_mar_sum": 860.0,          # 80 - 20 + 400 + 400 (id 3 is blank)
    }
    checks = {
        "sum_amount": e.amount.sum(), "mean_amount": e.amount.mean(), "median_amount": e.amount.median(),
        "missing_amount": int(e.amount.isna().sum()), "rows": len(e),
        "city_sum": e.groupby("city").amount.sum().to_dict(), "qty_ge_2": int((e.qty >= 2).sum()),
        "feb_mar_sum": e[(e.date >= "2025-02-01") & (e.date <= "2025-03-31")].amount.sum(),
    }
    for k, v in HAND.items():
        got = checks[k]
        ok = all(abs(got[g] - x) < 1e-9 for g, x in v.items()) if isinstance(v, dict) else abs(got - v) < 1e-9
        assert ok, f"hand value {k}={v} disagrees with pandas {got}"

    q = d.order_date.dt.to_period("Q").astype(str)
    m = d.order_date.dt.to_period("M").astype(str)
    by_region = d.groupby("region").revenue.sum()
    q2 = d[q == "2025Q2"].groupby("region").revenue.sum()
    q3 = d[q == "2025Q3"].groupby("region").revenue.sum()
    shares = d.channel.value_counts(normalize=True) * 100
    rating_by_channel = d.groupby("channel").customer_rating.mean()
    top5 = d.dropna(subset=["revenue"]).sort_values("revenue", ascending=False, kind="stable").head(5).order_id.tolist()
    ship_by_channel = d.groupby("channel").shipping_days.mean().sort_values()
    corr = d[["shipping_days", "customer_rating"]].dropna().corr().iloc[0, 1]

    N = lambda v, rel=1e-9, ab=1e-6: {"kind": "number", "value": r(v), "rel_tol": rel, "abs_tol": ab}  # noqa: E731
    cases = [
        # ----- retail sample: calculations
        dict(id="R01", category="sum", dataset="retail", question="What is the total revenue?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenue"}, extract={"type": "scalar"}, expected=N(d.revenue.sum())),
        dict(id="R02", category="average", dataset="retail", question="What is the average revenue per order?",
             operation={"type": "aggregate", "agg": "mean", "column": "revenue"}, extract={"type": "scalar"}, expected=N(d.revenue.mean())),
        dict(id="R03", category="median", dataset="retail", question="What is the median revenue?",
             operation={"type": "aggregate", "agg": "median", "column": "revenue"}, extract={"type": "scalar"}, expected=N(d.revenue.median())),
        dict(id="R04", category="count", dataset="retail", question="How many orders are there?",
             operation={"type": "aggregate", "agg": "count", "column": None}, extract={"type": "scalar"}, expected=N(len(d))),
        dict(id="R05", category="filter", dataset="retail", question="How many orders came from the West region?",
             operation={"type": "aggregate", "agg": "count", "column": None, "filters": [{"column": "region", "op": "eq", "value": "West"}]},
             extract={"type": "scalar"}, expected=N((d.region == "West").sum())),
        dict(id="R06", category="grouping", dataset="retail", question="What is total revenue by region?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenue", "group_by": ["region"]},
             extract={"type": "table", "key": "region", "column": "total revenue"},
             expected={"kind": "table", "value": {k: r(v) for k, v in by_region.items()}, "rel_tol": 1e-9, "abs_tol": 1e-6}),
        dict(id="R07", category="ranking", dataset="retail", question="Which region has the highest total revenue?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenue", "group_by": ["region"], "sort": "desc"},
             extract={"type": "first", "column": "region"}, expected={"kind": "text", "value": by_region.idxmax()}),
        dict(id="R08", category="grouping", dataset="retail", question="What is the average customer rating by channel?",
             operation={"type": "aggregate", "agg": "mean", "column": "customer_rating", "group_by": ["channel"]},
             extract={"type": "table", "key": "channel", "column": "average customer_rating"},
             expected={"kind": "table", "value": {k: r(v) for k, v in rating_by_channel.items()}, "rel_tol": 1e-9, "abs_tol": 1e-6}),
        dict(id="R09", category="multi-condition filter", dataset="retail", question="How many West online orders had at least 3 units?",
             operation={"type": "aggregate", "agg": "count", "column": None, "filters": [
                 {"column": "region", "op": "eq", "value": "West"}, {"column": "channel", "op": "eq", "value": "Online"}, {"column": "units", "op": "gte", "value": 3}]},
             extract={"type": "scalar"}, expected=N(((d.region == "West") & (d.channel == "Online") & (d.units >= 3)).sum())),
        dict(id="R10", category="date filter", dataset="retail", question="What was total revenue in Q3 2025 (July to September)?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenue", "filters": [{"column": "order_date", "op": "between", "value": ["2025-07-01", "2025-09-30"]}]},
             extract={"type": "scalar"}, expected=N(d[(d.order_date >= "2025-07-01") & (d.order_date <= "2025-09-30")].revenue.sum())),
        dict(id="R11", category="trend", dataset="retail", question="How did total revenue change month by month?",
             operation={"type": "trend", "date_column": "order_date", "agg": "sum", "value_column": "revenue", "granularity": "month"},
             extract={"type": "table", "key": "period", "column": "total revenue"},
             expected={"kind": "table", "value": {k: r(v) for k, v in d.groupby(m).revenue.sum().items()}, "rel_tol": 1e-9, "abs_tol": 1e-6}),
        dict(id="R12", category="comparison", dataset="retail", question="By how much did West's revenue change from Q2 to Q3 2025?",
             operation={"type": "period_change", "date_column": "order_date", "agg": "sum", "value_column": "revenue", "granularity": "quarter",
                        "period_a": "2025-Q2", "period_b": "2025-Q3", "group_by": "region", "sort": "asc"},
             extract={"type": "cell", "match": {"region": "West"}, "column": "change"}, expected=N(q3["West"] - q2["West"])),
        dict(id="R13", category="comparison", dataset="retail", question="Which region's revenue dropped most from Q2 to Q3 2025?",
             operation={"type": "period_change", "date_column": "order_date", "agg": "sum", "value_column": "revenue", "granularity": "quarter",
                        "period_a": "2025-Q2", "period_b": "2025-Q3", "group_by": "region", "sort": "asc"},
             extract={"type": "first", "column": "region"}, expected={"kind": "text", "value": (q3 - q2).idxmin()}),
        dict(id="R14", category="percentage", dataset="retail", question="What percentage of orders were placed online?",
             operation={"type": "distribution", "column": "channel"},
             extract={"type": "cell", "match": {"channel": "Online"}, "column": "share"}, expected=N(shares["Online"], rel=0, ab=0.05)),
        dict(id="R15", category="sorting", dataset="retail", question="What are the 5 largest orders by revenue?",
             operation={"type": "top_rows", "sort_by": "revenue", "order": "desc", "n": 5}, extract={"type": "column_list", "column": "order_id"},
             expected={"kind": "list", "value": top5}),
        dict(id="R16", category="ranking", dataset="retail", question="Which channel ships fastest on average?",
             operation={"type": "aggregate", "agg": "mean", "column": "shipping_days", "group_by": ["channel"], "sort": "asc"},
             extract={"type": "first", "column": "channel"}, expected={"kind": "text", "value": ship_by_channel.index[0]}),
        dict(id="R17", category="count", dataset="retail", question="How many distinct products are there?",
             operation={"type": "aggregate", "agg": "nunique", "column": "product"}, extract={"type": "scalar"}, expected=N(d["product"].nunique())),
        dict(id="R18", category="duplicates", dataset="retail", question="How many rows does the file have, and are duplicates flagged?",
             operation={"type": "aggregate", "agg": "count", "column": None}, extract={"type": "scalar"},
             expected=N(len(d)), expect_warning=f"{int(d.duplicated().sum())} duplicate rows"),
        dict(id="R19", category="missing values", dataset="retail", question="What is the average customer rating, and are missing ratings disclosed?",
             operation={"type": "aggregate", "agg": "mean", "column": "customer_rating"}, extract={"type": "scalar"},
             expected=N(d.customer_rating.mean()), expect_warning=f"{int(d.customer_rating.isna().sum())} rows"),
        dict(id="R20", category="misleading correlation", dataset="retail", question="Do longer shipping times cause lower ratings?",
             operation={"type": "correlation", "column_x": "shipping_days", "column_y": "customer_rating"}, extract={"type": "scalar"},
             expected=N(corr, rel=0, ab=1e-4), expect_warning="not that one causes the other"),
        # ----- retail sample: invalid requests must be refused, not answered
        dict(id="R21", category="incorrect column name", dataset="retail", question="What is the total revenu?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenu"}, extract={"type": "error"},
             expected={"kind": "error_contains", "value": "no column called 'revenu'"}),
        dict(id="R22", category="wrong column type", dataset="retail", question="What is the sum of region?",
             operation={"type": "aggregate", "agg": "sum", "column": "region"}, extract={"type": "error"},
             expected={"kind": "error_contains", "value": "needs a numeric column"}),
        dict(id="R23", category="empty result", dataset="retail", question="What is the revenue of orders with more than 1,000 units?",
             operation={"type": "aggregate", "agg": "sum", "column": "revenue", "filters": [{"column": "units", "op": "gt", "value": 1000}]},
             extract={"type": "error"}, expected={"kind": "error_contains", "value": "No rows match"}),
        dict(id="R24", category="invalid value", dataset="retail", question="How many orders came from Atlantis?",
             operation={"type": "aggregate", "agg": "count", "column": None, "filters": [{"column": "region", "op": "eq", "value": "Atlantis"}]},
             extract={"type": "error"}, expected={"kind": "error_contains", "value": "doesn't appear in region"}),
        # ----- hand-verified edge dataset
        dict(id="E01", category="sum with nulls", dataset="edge", question="What is the total amount?",
             operation={"type": "aggregate", "agg": "sum", "column": "amount"}, extract={"type": "scalar"}, expected=N(HAND["sum_amount"]),
             expect_warning="2 rows"),
        dict(id="E02", category="average with nulls", dataset="edge", question="What is the average amount?",
             operation={"type": "aggregate", "agg": "mean", "column": "amount"}, extract={"type": "scalar"}, expected=N(HAND["mean_amount"])),
        dict(id="E03", category="median (even count)", dataset="edge", question="What is the median amount?",
             operation={"type": "aggregate", "agg": "median", "column": "amount"}, extract={"type": "scalar"}, expected=N(HAND["median_amount"])),
        dict(id="E04", category="missing values", dataset="edge", question="How many rows have no amount?",
             operation={"type": "aggregate", "agg": "count", "column": None, "filters": [{"column": "amount", "op": "is_null"}]},
             extract={"type": "scalar"}, expected=N(HAND["missing_amount"])),
        dict(id="E05", category="duplicates", dataset="edge", question="How many rows are there?",
             operation={"type": "aggregate", "agg": "count", "column": None}, extract={"type": "scalar"}, expected=N(HAND["rows"]),
             expect_warning="1 duplicate rows"),
        dict(id="E06", category="grouping with negatives", dataset="edge", question="What is the total amount by city?",
             operation={"type": "aggregate", "agg": "sum", "column": "amount", "group_by": ["city"]},
             extract={"type": "table", "key": "city", "column": "total amount"},
             expected={"kind": "table", "value": HAND["city_sum"], "rel_tol": 1e-9, "abs_tol": 1e-9}),
        dict(id="E07", category="numeric filter", dataset="edge", question="How many rows have a quantity of at least 2?",
             operation={"type": "aggregate", "agg": "count", "column": None, "filters": [{"column": "qty", "op": "gte", "value": 2}]},
             extract={"type": "scalar"}, expected=N(HAND["qty_ge_2"])),
        dict(id="E08", category="date filter", dataset="edge", question="What was the total amount in February and March 2025?",
             operation={"type": "aggregate", "agg": "sum", "column": "amount", "filters": [{"column": "date", "op": "between", "value": ["2025-02-01", "2025-03-31"]}]},
             extract={"type": "scalar"}, expected=N(HAND["feb_mar_sum"])),
    ]
    # Natural-language interpretation cases (AI track): the question alone is sent through the normal /ask path.
    ai_ids = {"R01", "R02", "R05", "R06", "R07", "R09", "R10", "R13", "R16", "R17"}
    for c in cases:
        c["ai"] = c["id"] in ai_ids
    ambiguous = [
        dict(id="A01", category="unanswerable", dataset="retail", question="What is the average profit by region?", operation=None, ai=True,
             extract={"type": "status"}, expected={"kind": "status", "value": "unanswerable"}),
        dict(id="A02", category="unanswerable", dataset="retail", question="How many customers are over 40 years old?", operation=None, ai=True,
             extract={"type": "status"}, expected={"kind": "status", "value": "unanswerable"}),
    ]
    suite = {
        "suite": "datalens-accuracy",
        "version": 1,
        "generated_by": "scripts/compute_benchmark_expectations.py (plain pandas, independent of app code; edge values also hand-verified)",
        "datasets": {
            "retail": {"path": "sample-data/retail_sales_2025.csv", "sha256": sha256(RETAIL), "rows": len(d)},
            "edge": {"path": "backend/benchmarks/edge_cases_v1.csv", "sha256": sha256(EDGE), "rows": len(e)},
        },
        "cases": cases + ambiguous,
    }
    OUT.write_text(json.dumps(suite, indent=1, default=str) + "\n")
    print(f"Wrote {len(suite['cases'])} cases to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
