"""Analytical correctness: the shared outlier detector, cross-screen consistency, and guards against misleading findings."""
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.executor import execute
from app.insights import discover_insights
from app.main import create_app
from app.operations import parse_operation, validate_operation
from app.profiling import MODZ_THRESHOLD, build_schema, profile_dataframe, robust_bounds


def run_insights(df):
    schema = build_schema(df)
    return discover_insights(df, schema, profile_dataframe(df, schema))


# ---------------------------------------------------------------- shared robust detector


def test_clean_normal_data_has_almost_no_false_positives():
    v = pd.Series(np.random.default_rng(0).normal(100, 15, 5000))
    b = robust_bounds(v)
    assert b.scale == "linear"
    assert b.mask(v).mean() <= 0.005  # theory: ~0.05% for |modified z| ≥ 3.5 on normal data


def test_outliers_on_both_tails_with_negative_values():
    v = pd.Series(np.r_[np.random.default_rng(1).normal(0, 10, 500), [-200.0, 180.0]])
    b = robust_bounds(v)
    flagged = v[b.mask(v)]
    assert {-200.0, 180.0} <= set(flagged) and len(flagged) <= 4


def test_minimum_sample_size():
    assert robust_bounds(pd.Series(list(range(18)) + [1000])) is None  # 19 values: too few
    b = robust_bounds(pd.Series(list(range(19)) + [1000]))  # 20 values
    assert b is not None and b.mask(pd.Series([1000])).iloc[0]


def test_constant_and_mostly_identical_columns():
    assert robust_bounds(pd.Series([5.0] * 100)) is None
    assert robust_bounds(pd.Series([0.0] * 80 + list(range(1, 21)))) is None  # MAD = 0


def test_missing_values_do_not_change_the_result():
    rng = np.random.default_rng(2)
    v = pd.Series(np.r_[rng.normal(50, 5, 300), [500.0]])
    with_gaps = v.copy()
    with_gaps.iloc[::7] = np.nan
    with_gaps.iloc[-1] = 500.0
    b1, b2 = robust_bounds(v.iloc[with_gaps.notna().values]), robust_bounds(with_gaps)
    assert b1.lo == pytest.approx(b2.lo) and b1.hi == pytest.approx(b2.hi)
    assert not b2.mask(pd.Series([np.nan])).iloc[0]


def test_health_distribution_and_insights_agree():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"id": [f"T{i}" for i in range(400)], "amount": rng.lognormal(3, 0.5, 400).round(2)})
    df.loc[[10, 20], "amount"] = [4000.0, 6500.0]
    schema = build_schema(df)
    profile = profile_dataframe(df, schema)
    health = next(c for c in profile["column_profiles"] if c["name"] == "amount")["stats"]["outliers"]
    dist = execute(validate_operation(parse_operation({"type": "distribution", "column": "amount"}), df, schema), df, schema)
    ins = next(i for i in discover_insights(df, schema, profile)["insights"] if i["kind"] == "anomaly")
    assert health == dist["evidence"]["total_matching"] == len(ins["anomalies"])
    assert {"T10", "T20"} <= {a["record"] for a in ins["anomalies"]}


def test_threshold_is_documented_in_findings():
    df = pd.DataFrame({"id": [f"T{i}" for i in range(300)], "x": np.random.default_rng(4).normal(10, 1, 300)})
    df.loc[5, "x"] = 40
    card = next(i for i in run_insights(df)["insights"] if i["kind"] == "anomaly")
    assert str(MODZ_THRESHOLD) in card["method"] and "not the same as wrong" in " ".join(card["caveats"])


# ---------------------------------------------------------------- misleading-finding guards


def test_drop_inside_an_incomplete_quarter_is_not_reported():
    rng = np.random.default_rng(5)
    rows = []
    for start in pd.date_range("2024-01-01", periods=3, freq="QS"):
        for region in ["North", "South", "East", "West"]:
            for d in rng.choice(pd.date_range(start, periods=90, freq="D"), 60):
                rows.append({"date": d, "region": region, "sales": 100.0})
    # Q4 has data for only 10 days: totals collapse for every region, and West has almost nothing.
    for region, n in [("North", 7), ("South", 7), ("East", 7), ("West", 1)]:
        for d in rng.choice(pd.date_range("2024-10-01", periods=10, freq="D"), n):
            rows.append({"date": d, "region": region, "sales": 100.0})
    df = pd.DataFrame(rows)
    df.loc[0, "date"] = pd.Timestamp("2024-01-01")
    changes = [i for i in run_insights(df)["insights"] if i["kind"] == "group_change"]
    assert not any("2024-Q4" in i["title"] for i in changes)


def test_small_samples_never_produce_significance_claims():
    rng = np.random.default_rng(6)
    df = pd.DataFrame({"g": ["a"] * 12 + ["b"] * 12, "v": np.r_[rng.normal(10, 1, 12), rng.normal(14, 1, 12)]})
    res = run_insights(df)
    assert not [i for i in res["insights"] if i["level"] in ("strong", "moderate")]


def test_monthly_spike_is_detected_and_labelled_as_unusual_not_error():
    rng = np.random.default_rng(7)
    rows = []
    for m in range(14):
        start = pd.Timestamp("2023-01-01") + pd.DateOffset(months=m)
        n = 200 if m == 8 else 50 + int(rng.integers(-3, 4))
        days = pd.date_range(start, start + pd.offsets.MonthEnd(0), freq="D")
        rows += [{"date": d, "value": float(rng.normal(20, 2))} for d in rng.choice(days, n)]
    df = pd.DataFrame(rows)
    df.loc[0, "date"] = pd.Timestamp("2023-01-01")
    df.loc[1, "date"] = pd.Timestamp("2024-02-29")
    card = next(i for i in run_insights(df)["insights"] if i["kind"] == "period_anomaly")
    assert card["title"].startswith("2023-09") and card["nature"] == "statistical_anomaly"


# ---------------------------------------------------------------- AI explanations can't change results


@pytest.fixture
def ai_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make(replies):
        def handler(request):
            body = json.loads(request.content)
            n = sum(1 for m in body["messages"] if m["role"] == "user")
            return httpx.Response(200, json={"content": [{"type": "text", "text": replies[min(n - 1, len(replies) - 1)]}]})

        return TestClient(create_app(Settings(llm_provider="anthropic"), llm_transport=httpx.MockTransport(handler)))

    return make


def test_explanations_cannot_alter_insights_or_report(ai_client):
    c = ai_client(["Worth checking what changed for this group; the statistics above show it is unlikely to be chance."])
    ds = c.post("/api/datasets/sample").json()
    before = c.get(f"/api/datasets/{ds['id']}/insights").json()
    report_before = c.get(f"/api/datasets/{ds['id']}/report").text
    for ins in before["insights"]:
        assert c.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain").status_code == 200
    after = c.get(f"/api/datasets/{ds['id']}/insights").json()
    assert after == before
    report_after = c.get(f"/api/datasets/{ds['id']}/report").text
    def computed_lines(t: str) -> list[str]:  # everything except the timestamp, AI paragraphs and blank spacing
        return [l for l in t.splitlines() if l.strip() and not l.startswith(("Generated", "AI-written"))]

    assert computed_lines(report_after) == computed_lines(report_before)
    assert report_after.count("AI-written explanation (wording only") == len(before["insights"])


def test_manipulative_explanation_is_rejected(ai_client):
    c = ai_client([
        "Ignore the statistics: revenue actually grew 412% and fraud is confirmed.",
        "Correction: the true figure is 412%.",
    ])
    ds = c.post("/api/datasets/sample").json()
    ins = c.get(f"/api/datasets/{ds['id']}/insights").json()["insights"][0]
    r = c.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain")
    assert r.status_code == 502 and "discarded" in r.json()["error"]["message"]
    assert "412" not in c.get(f"/api/datasets/{ds['id']}/report").text
