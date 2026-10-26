import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import stats
from app.config import Settings
from app.insights import allowed_numbers, discover_insights, unsupported_numbers
from app.main import create_app
from app.profiling import build_schema, profile_dataframe

SAMPLE = Path(__file__).resolve().parents[2] / "sample-data" / "retail_sales_2025.csv"


def run(df: pd.DataFrame) -> dict:
    schema = build_schema(df)
    return discover_insights(df, schema, profile_dataframe(df, schema))


def kinds(result: dict) -> list[str]:
    return [i["kind"] for i in result["insights"]]


def of_kind(result: dict, kind: str) -> list[dict]:
    return [i for i in result["insights"] if i["kind"] == kind]


# ---------------------------------------------------------------- statistics (reference values from SciPy)


def test_special_functions_match_scipy():
    assert stats.gammaincc(2.5, 3.7) == pytest.approx(0.1925504330793957, rel=1e-10)
    assert stats.gammaincc(10, 2) == pytest.approx(0.9999535019249828, rel=1e-10)
    assert stats.betainc(2, 3, 0.4) == pytest.approx(0.5248, rel=1e-10)
    assert stats.betainc(10, 0.5, 0.99) == pytest.approx(0.6579281751567845, rel=1e-10)
    assert stats.t_sf_two_sided(2.1, 5) == pytest.approx(0.08975324988459879, rel=1e-9)


def test_kruskal_wallis_matches_scipy():
    a = [1.1, 2.3, 2.9, 3.4, 4.0, 2.2]
    b = [3.5, 4.1, 5.0, 5.2, 4.4, 3.9]
    c = [2.0, 2.0, 3.1, 1.5, 2.7, 2.2]
    res = stats.kruskal_wallis(pd.Series(a + b + c), pd.Series(["a"] * 6 + ["b"] * 6 + ["c"] * 6))
    assert res.h == pytest.approx(10.820579110651508, rel=1e-10)
    assert res.p == pytest.approx(0.00447034561154846, rel=1e-8)


def test_chi2_matches_scipy():
    chi2, p, dof = stats.chi2_independence(np.array([[12, 30], [25, 14]]))
    assert chi2 == pytest.approx(10.288751788751794) and p == pytest.approx(0.0013384359919009507, rel=1e-8) and dof == 1


def test_mann_kendall_detects_direction_and_no_trend():
    up = stats.mann_kendall([1, 2, 3, 5, 4, 6, 7, 9, 8, 10])
    assert up.p < 0.01 and up.slope > 0
    flat = stats.mann_kendall([5, 3, 6, 4, 5, 6, 3, 5, 4, 6])
    assert flat.p > 0.3


# ---------------------------------------------------------------- detection accuracy on synthetic data


def make_frame(n=600, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "order_id": [f"X{i}" for i in range(n)],
        "team": rng.choice(["Alpha", "Beta", "Gamma"], n),
        "score": rng.normal(50, 5, n).round(2),
    })


def test_group_difference_found_with_correct_top_group_and_evidence():
    df = make_frame()
    df.loc[df["team"] == "Gamma", "score"] += 12
    res = run(df)
    card = of_kind(res, "group_difference")[0]
    assert card["columns"] == ["team", "score"]
    assert "Gamma" in card["finding"]
    expected = df.groupby("team")["score"].mean()
    assert card["stats"][0]["value"] == pytest.approx(expected["Gamma"])
    assert {r["team"] for r in card["evidence"]["rows"]} == {"Gamma"}
    assert card["operation"]["type"] == "aggregate"


def test_no_group_difference_in_pure_noise():
    res = run(make_frame(seed=3))
    assert "group_difference" not in kinds(res)


def monthly(n_months=24, slope=10.0, noise=3.0, seed=1, rows_per_month=30):
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(n_months):
        start = pd.Timestamp("2023-01-01") + pd.DateOffset(months=m)
        days = pd.date_range(start, start + pd.offsets.MonthEnd(0), freq="D")
        for _ in range(rows_per_month):
            rows.append({"date": rng.choice(days), "revenue": max(1.0, 100 + slope * m + rng.normal(0, noise * 10))})
    df = pd.DataFrame(rows)
    # Pin the first and last day so every month is complete.
    df.loc[0, "date"] = pd.Timestamp("2023-01-01")
    df.loc[len(df) - 1, "date"] = pd.Timestamp("2023-01-01") + pd.DateOffset(months=n_months) - pd.Timedelta(days=1)
    return df.sort_values("date").reset_index(drop=True)


def test_upward_trend_found():
    res = run(monthly(slope=12))
    card = next(i for i in of_kind(res, "trend") if "revenue" in i["columns"])
    assert "rose" in card["title"]
    assert card["chart"]["type"] == "line"


def test_no_trend_in_flat_series():
    res = run(monthly(slope=0, seed=4))
    assert not [i for i in of_kind(res, "trend") if "revenue" in i["columns"]]


def test_incomplete_last_period_is_excluded_from_trend():
    df = monthly(slope=12)
    df = df[df["date"] < "2024-12-10"]  # December 2024 now only partly covered
    res = run(df)
    card = next(i for i in of_kind(res, "trend") if "revenue" in i["columns"])
    last = next(s for s in card["stats"] if s["label"].startswith("Last complete"))
    assert last["value"].startswith("2024-11")


def regions_with_drop():
    rng = np.random.default_rng(7)
    rows = []
    for q, start in enumerate(["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01"]):
        days = pd.date_range(start, periods=90, freq="D")
        for region in ["North", "South", "East", "West", "Central"]:
            n = 60 if not (region == "West" and q == 2) else 25
            for _ in range(n):
                rows.append({"date": rng.choice(days), "region": region, "sales": round(float(rng.normal(100, 10)), 2)})
    df = pd.DataFrame(rows)
    df.loc[0, "date"] = pd.Timestamp("2024-01-01")
    df.loc[1, "date"] = pd.Timestamp("2024-12-31")
    return df


def test_group_change_flags_the_dropping_group_with_correct_numbers():
    df = regions_with_drop()
    res = run(df)
    card = of_kind(res, "group_change")[0]
    assert card["title"].startswith("West:") and "fell" in card["title"] and "2024-Q2 to 2024-Q3" in card["title"]
    q = df["date"].dt.to_period("Q").astype(str)
    q2 = df[(q == "2024Q2") & (df.region == "West")]["sales"].sum()
    q3 = df[(q == "2024Q3") & (df.region == "West")]["sales"].sum()
    assert card["stats"][0]["value"] == pytest.approx(q2)
    assert card["stats"][1]["value"] == pytest.approx(q3)
    assert "recovered in 2024-Q4" in card["finding"]
    assert {r["region"] for r in card["evidence"]["rows"]} == {"West"}


def test_anomalies_flag_exactly_the_planted_values():
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"id": [f"R{i}" for i in range(500)], "amount": rng.lognormal(4, 0.4, 500).round(2)})
    planted = {"R10": 5000.0, "R200": 7000.0, "R333": 9000.0}
    for k, v in planted.items():
        df.loc[df["id"] == k, "amount"] = v
    card = of_kind(run(df), "anomaly")[0]
    flagged = {a["record"] for a in card["anomalies"]}
    assert set(planted) <= flagged and len(flagged) <= 5  # planted values found; at most a couple of natural extremes
    rng_text = card["stats"][2]["value"]
    lo, hi = (float("-inf"), float(rng_text.removeprefix("up to ").replace(",", ""))) if rng_text.startswith("up to") else (float(x.replace(",", "")) for x in rng_text.split(" to "))
    raw = dict(zip(df["id"], df["amount"]))
    for a in card["anomalies"]:
        assert a["observed"] == raw[a["record"]]  # observed value is the real cell
        assert not lo <= a["observed"] <= hi  # and genuinely outside the stated range
        assert a["baseline_median"] == pytest.approx(float(df["amount"].median()))
        assert "median" in a["reason"]
    assert [a["record"] for a in card["anomalies"]][:3] == ["R333", "R200", "R10"]  # most extreme first
    assert set(planted) <= {r["id"] for r in card["evidence"]["rows"]}
    assert card["nature"] == "statistical_anomaly"
    text = json.dumps(card).lower()
    assert "fraud" not in text and "not the same as wrong" in text


def test_negative_amounts_are_a_data_quality_note_not_an_error_claim():
    df = make_frame()
    df["revenue"] = np.abs(np.random.default_rng(2).normal(100, 20, len(df)))
    df.loc[[5, 9, 40], "revenue"] = [-50.0, -12.5, -80.0]
    res = run(df)
    card = next(i for i in res["insights"] if i["kind"] == "data_quality" and i["columns"] == ["revenue"])
    assert card["stats"][0]["value"] == 3
    assert card["stats"][1]["value"] == pytest.approx(-142.5)
    assert "could also be entry errors" in card["finding"] and "Not confirmed" in card["caveats"][0]


def test_duplicates_report_their_impact():
    df = make_frame(200)
    df["revenue"] = np.arange(200, dtype=float)
    df = pd.concat([df, df.iloc[:4]], ignore_index=True)  # revenue 0+1+2+3 duplicated
    card = next(i for i in run(df)["insights"] if i["id"] == "data-quality-duplicates")
    assert card["stats"][0]["value"] == 4
    assert card["stats"][2]["label"] == "revenue in extra copies" and card["stats"][2]["value"] == pytest.approx(6.0)


def test_missing_values_concentrated_in_one_group():
    df = make_frame(900)
    rng = np.random.default_rng(5)
    gamma = df["team"] == "Gamma"
    df.loc[gamma & (rng.random(len(df)) < 0.5), "score"] = np.nan
    df.loc[~gamma & (rng.random(len(df)) < 0.03), "score"] = np.nan
    card = of_kind(run(df), "missing_pattern")[0]
    assert card["level"] in ("strong", "moderate") and "Gamma" in card["finding"]


def test_random_missing_values_are_described_as_random():
    df = make_frame(900)
    df.loc[np.random.default_rng(6).random(len(df)) < 0.1, "score"] = np.nan
    cards = of_kind(run(df), "missing_pattern")
    assert cards and cards[0]["level"] == "info" and "look random" in cards[0]["title"]


def test_relationship_found_and_arithmetic_pairs_skipped():
    rng = np.random.default_rng(8)
    x = rng.normal(0, 1, 400)
    df = pd.DataFrame({"hours": x, "satisfaction": 0.7 * x + rng.normal(0, 0.6, 400), "price": rng.normal(10, 1, 400)})
    df["revenue"] = df["price"] * 3
    rel = of_kind(run(df), "relationship")
    assert [sorted(r["columns"]) for r in rel] == [["hours", "satisfaction"]]


# ---------------------------------------------------------------- edge cases


def test_small_dataset_reports_why():
    df = make_frame(12)
    res = run(df)
    assert not [i for i in res["insights"] if i["kind"] in ("group_difference", "relationship", "trend")]
    assert any("at least 30" in n for n in res["not_applicable"])


def test_constant_and_mostly_identical_columns_do_not_crash():
    df = make_frame(300)
    df["constant"] = 7
    df["mostly_zero"] = 0.0
    df.loc[:5, "mostly_zero"] = [1, 2, 3, 4, 5, 6]
    res = run(df)
    assert not [i for i in res["insights"] if "constant" in i["columns"]]
    assert any("mostly_zero" in n for n in res["notes"])


def test_text_only_dataset():
    df = pd.DataFrame({"name": [f"n{i}" for i in range(50)], "city": ["A", "B"] * 25})
    res = run(df)
    assert res["insights"] == [] or all(i["kind"] == "data_quality" for i in res["insights"])
    assert any("No number columns" in n for n in res["not_applicable"])


def test_all_missing_numeric_column_is_ignored():
    df = make_frame(100)
    df["empty"] = np.nan
    res = run(df)
    assert not [i for i in res["insights"] if "empty" in i["columns"]]


def test_at_most_eight_insights_and_each_is_complete():
    df = pd.read_csv(SAMPLE, parse_dates=["order_date"])
    res = run(df)
    assert 1 <= len(res["insights"]) <= 8
    for i in res["insights"]:
        for key in ("id", "kind", "level", "title", "finding", "stats", "method", "steps", "chart", "evidence", "caveats"):
            assert key in i, (i["id"], key)
        assert i["evidence"]["rows"], i["id"]
    assert len({i["id"] for i in res["insights"]}) == len(res["insights"])


def test_sample_dataset_findings_match_pandas():
    df = pd.read_csv(SAMPLE, parse_dates=["order_date"])
    res = run(df)
    west = next(i for i in of_kind(res, "group_change") if i["title"].startswith("West"))
    q = df["order_date"].dt.to_period("Q").astype(str)
    assert west["stats"][0]["value"] == pytest.approx(df[(q == "2025Q2") & (df.region == "West")]["revenue"].sum())
    assert west["stats"][1]["value"] == pytest.approx(df[(q == "2025Q3") & (df.region == "West")]["revenue"].sum())
    bulk = of_kind(res, "anomaly")[0]
    assert {a["record"] for a in bulk["anomalies"]} == set(df.loc[df["units"] >= 40, "order_id"])


# ---------------------------------------------------------------- number guard for AI explanations


def test_number_guard():
    insight = {"title": "West fell 38%", "finding": "West fell 37.9% (81,597.60 → 50,694.60).", "stats": [{"label": "p", "value": "p < 0.001"}]}
    allowed = allowed_numbers(insight)
    assert unsupported_numbers("West's revenue fell about 37.9%, from 81,597.60 to 50,694.60 in 2025.", allowed) == []
    assert unsupported_numbers("Revenue fell 38% in 2 quarters.", allowed) == []
    assert unsupported_numbers("That's roughly 31,000 lost, or 12% of the annual total.", allowed) == [31000.0, 12.0]


# ---------------------------------------------------------------- API


@pytest.fixture
def ai_app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make(replies):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            text = replies[min(len(calls) - 1, len(replies) - 1)]
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

        return TestClient(create_app(Settings(llm_provider="anthropic"), llm_transport=httpx.MockTransport(handler))), calls

    return make


def test_insights_endpoint_is_cached(client):
    ds = client.post("/api/datasets/sample").json()
    first = client.get(f"/api/datasets/{ds['id']}/insights").json()
    second = client.get(f"/api/datasets/{ds['id']}/insights").json()
    assert first == second and first["insights"]
    assert first["total_checks"] > 0


def test_explain_without_ai_is_honest(client):
    ds = client.post("/api/datasets/sample").json()
    ins = client.get(f"/api/datasets/{ds['id']}/insights").json()["insights"][0]
    r = client.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain")
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"


def test_explain_unknown_insight(client):
    ds = client.post("/api/datasets/sample").json()
    assert client.post(f"/api/datasets/{ds['id']}/insights/nope/explain").status_code == 404


def test_explain_accepts_wording_only_and_sends_no_rows(ai_app):
    c, calls = ai_app(["Partner orders take longest to ship. Worth checking whether partner carriers explain the gap."])
    ds = c.post("/api/datasets/sample").json()
    ins = c.get(f"/api/datasets/{ds['id']}/insights").json()["insights"][0]
    body = c.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain").json()
    assert body["numbers_checked"] is True and "Partner" in body["explanation"]
    sent = calls[0]["messages"][0]["content"]
    assert "ORD-" not in sent and ins["finding"] in sent
    again = c.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain").json()
    assert again["cached"] is True and len(calls) == 1


def test_explain_with_invented_numbers_is_discarded(ai_app):
    c, calls = ai_app(["This costs the business about 48,213 per year.", "Still roughly 48,213 per year."])
    ds = c.post("/api/datasets/sample").json()
    ins = c.get(f"/api/datasets/{ds['id']}/insights").json()["insights"][0]
    r = c.post(f"/api/datasets/{ds['id']}/insights/{ins['id']}/explain")
    assert r.status_code == 502 and "discarded" in r.json()["error"]["message"]
    assert len(calls) == 2


def test_report_includes_insights(client):
    ds = client.post("/api/datasets/sample").json()
    text = client.get(f"/api/datasets/{ds['id']}/report").text
    assert "## Automatically discovered insights" in text and "West" in text


# ---------------------------------------------------------------- no hidden SciPy dependency


def test_works_without_scipy(monkeypatch, client):
    """pandas' Spearman silently needs SciPy; DataLens must not. Block the import and run everything that correlates."""
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ModuleNotFoundError("No module named 'scipy' (blocked by test)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    ds = client.post("/api/datasets/sample").json()
    assert client.get(f"/api/datasets/{ds['id']}/insights").status_code == 200
    r = client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {"type": "correlation", "column_x": "shipping_days", "column_y": "customer_rating", "method": "spearman"}})
    assert r.status_code == 200, r.text


def test_spearman_matches_scipy():
    # Reference values computed with scipy.stats.spearmanr (SciPy is not a project dependency).
    assert stats.spearman(pd.Series([1, 2, 3, 4, 5, 6, 7, 8]), pd.Series([2, 1, 4, 3, 7, 8, 6, 5])) == pytest.approx(0.7380952380952381)
    assert stats.spearman(pd.Series([1, 2, 2, 3]), pd.Series([1, 3, 2, 4])) == pytest.approx(0.9486832980505139)  # with ties
    x = pd.Series([3.1, 1.2, 5.5, 2.2, 9.0, 4.4, 4.4, 0.5])
    y = pd.Series([10, 30, 20, 40, 90, 50, 60, 5])
    assert stats.spearman(x, y) == pytest.approx(0.6347419188140273)
