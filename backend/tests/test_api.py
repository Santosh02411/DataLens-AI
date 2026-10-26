import io
import json
from pathlib import Path

import httpx
import pandas as pd
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


import pytest


@pytest.fixture
def ai_client(monkeypatch):
    """Factory: app wired to a fake Anthropic endpoint that returns `replies` in order."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make(replies, status=200, raw=None):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append({"url": str(request.url), "body": json.loads(request.content), "headers": dict(request.headers)})
            if raw is not None:
                return httpx.Response(status, json=raw)
            text = replies[min(len(calls) - 1, len(replies) - 1)]
            return httpx.Response(status, json={"content": [{"type": "text", "text": text}]})

        app = create_app(Settings(llm_provider="anthropic"), llm_transport=httpx.MockTransport(handler))
        return TestClient(app), calls

    return make


def test_status_without_ai(client):
    body = client.get("/api/status").json()
    assert body["ai"]["configured"] is False and body["sample_available"] is True


def test_sample_profile_and_suggestions(client):
    ds = client.post("/api/datasets/sample").json()
    assert ds["rows"] > 1000
    profile = client.get(f"/api/datasets/{ds['id']}/profile").json()
    assert profile["duplicate_rows"] > 0
    assert any(i["title"] == "Duplicate rows" for i in profile["issues"])
    sugg = client.get(f"/api/datasets/{ds['id']}/suggestions").json()["suggestions"]
    assert len(sugg) >= 5
    for s in sugg:
        r = client.post(f"/api/datasets/{ds['id']}/run", json={"operation": s["operation"], "question": s["question"]})
        assert r.status_code == 200, r.text


def test_upload_csv_and_rows(client):
    csv = b"name,score\nA,1\nB,5\nC,3\n"
    ds = client.post("/api/datasets", files={"file": ("s.csv", csv, "text/csv")}).json()
    rows = client.get(f"/api/datasets/{ds['id']}/rows", params={"sort": "score", "order": "desc"}).json()
    assert [r["score"] for r in rows["rows"]] == [5, 3, 1]


def test_upload_xlsx(client):
    buf = io.BytesIO()
    pd.DataFrame({"a": [1, 2]}).to_excel(buf, index=False)
    r = client.post("/api/datasets", files={"file": ("b.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["rows"] == 2


def test_upload_rejects_bad_type(client):
    r = client.post("/api/datasets", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_type"


def test_upload_size_limit():
    c = TestClient(create_app(Settings(llm_provider=None, max_upload_mb=1)))
    r = c.post("/api/datasets", files={"file": ("big.csv", b"a\n" + b"1\n" * 600_000, "text/csv")})
    assert r.status_code == 413


def test_ask_without_ai_is_explained(client):
    ds = client.post("/api/datasets/sample").json()
    r = client.post(f"/api/datasets/{ds['id']}/ask", json={"question": "total revenue by region"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"


def test_unknown_dataset(client):
    assert client.get("/api/datasets/nope/profile").status_code == 404


def test_ask_with_ai_executes_validated_operation(ai_client):
    reply = json.dumps({"intent": "Total revenue per region", "operation": {"type": "aggregate", "agg": "sum", "column": "revenue", "group_by": ["region"]}})
    c, calls = ai_client([reply])
    ds = c.post("/api/datasets/sample").json()
    body = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "Which region sells the most?"}).json()
    assert body["status"] == "answered" and body["mode"] == "ai"
    assert body["intent"] == "Total revenue per region"
    # The prompt carries the schema, not raw rows.
    system = calls[0]["body"]["system"]
    assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == "test-key"
    assert '"revenue" (numeric)' in system and "ORD-10001" not in system


def test_ai_invalid_operation_is_retried_then_corrected(ai_client):
    bad = json.dumps({"intent": "x", "operation": {"type": "aggregate", "agg": "sum", "column": "profit"}})
    good = json.dumps({"intent": "x", "operation": {"type": "unanswerable", "reason": "There is no profit column.", "missing": ["profit"]}})
    c, calls = ai_client([bad, good])
    ds = c.post("/api/datasets/sample").json()
    body = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "What is total profit?"}).json()
    assert len(calls) == 2
    assert body["status"] == "unanswerable" and body["ai_attempts"] == 2


def test_ai_code_injection_never_runs(ai_client):
    evil = json.dumps({"intent": "x", "operation": {"type": "python", "code": "__import__('os').system('rm -rf /')"}})
    c, calls = ai_client([evil, evil])
    ds = c.post("/api/datasets/sample").json()
    r = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "delete everything"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_understood"


def test_report_download(client):
    ds = client.post("/api/datasets/sample").json()
    client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {"type": "aggregate", "agg": "count"}, "question": "How many rows?"})
    r = client.get(f"/api/datasets/{ds['id']}/report")
    assert r.status_code == 200 and "How many rows?" in r.text and "attachment" in r.headers["content-disposition"]


def test_ai_rejected_key_is_reported(ai_client):
    c, _ = ai_client([], status=401, raw={"error": {"message": "invalid x-api-key"}})
    ds = c.post("/api/datasets/sample").json()
    r = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "total revenue"})
    assert r.status_code == 502 and "rejected the API key" in r.json()["error"]["message"]
    assert "test-key" not in r.text


def test_ai_unexpected_response_shape_is_reported(ai_client):
    c, _ = ai_client([], raw={"something": "else"})
    ds = c.post("/api/datasets/sample").json()
    r = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "total revenue"})
    assert r.status_code in (422, 502)
    assert r.json()["error"]["code"] in ("ai_error", "not_understood")


def test_ai_non_json_twice_is_not_understood(ai_client):
    c, calls = ai_client(["Sure! The answer is 42.", "I think it's about 42."])
    ds = c.post("/api/datasets/sample").json()
    r = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "what is the answer"})
    assert r.status_code == 422 and len(calls) == 2
    assert "42" not in json.dumps(r.json()["error"]["message"])


def test_llm_base_url_override(ai_client, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gateway.local/")
    c, calls = ai_client([json.dumps({"intent": "x", "operation": {"type": "aggregate", "agg": "count"}})])
    ds = c.post("/api/datasets/sample").json()
    assert c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "how many rows"}).status_code == 200
    assert calls[0]["url"] == "http://gateway.local/v1/messages"


def test_sample_story_matches_independent_pandas(client):
    """The demo answer must equal a calculation done directly with pandas."""
    raw = pd.read_csv(Path(__file__).resolve().parents[2] / "sample-data" / "retail_sales_2025.csv", parse_dates=["order_date"])
    q = raw["order_date"].dt.to_period("Q").astype(str)
    q2 = raw[q == "2025Q2"].groupby("region")["revenue"].sum()
    q3 = raw[q == "2025Q3"].groupby("region")["revenue"].sum()
    change = (q3 - q2).sort_values()
    ds = client.post("/api/datasets/sample").json()
    body = client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {
        "type": "period_change", "date_column": "order_date", "value_column": "revenue", "granularity": "quarter",
        "period_a": "2025-Q2", "period_b": "2025-Q3", "group_by": "region", "sort": "asc"}}).json()
    top = body["result"]["rows"][0]
    assert top["region"] == change.index[0] == "West"
    assert top["change"] == pytest.approx(change.iloc[0])
    assert top["2025-Q2"] == pytest.approx(q2["West"])
    assert not any("incomplete" in w for w in body["warnings"])


def test_empty_filter_result_is_an_honest_error(client):
    ds = client.post("/api/datasets/sample").json()
    r = client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {"type": "aggregate", "agg": "sum", "column": "revenue",
        "filters": [{"column": "units", "op": "gt", "value": 100000}]}})
    assert r.status_code == 422 and "No rows match" in r.json()["error"]["message"]


def test_grouped_date_max_has_no_bar_chart(client):
    ds = client.post("/api/datasets/sample").json()
    body = client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {"type": "aggregate", "agg": "max", "column": "order_date", "group_by": ["region"]}}).json()
    assert body["chart"]["type"] == "none" and body["result"]["rows"][0]["maximum order_date"] == "2025-12-31"


def test_report_with_unicode_filename(client):
    ds = client.post("/api/datasets", files={"file": ("बिक्री ₹.csv", "शहर,राशि\nपुणे,10\n".encode(), "text/csv")}).json()
    r = client.get(f"/api/datasets/{ds['id']}/report")
    assert r.status_code == 200 and "filename*=UTF-8''" in r.headers["content-disposition"]


def test_excel_sheet_selection(client):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame().to_excel(w, sheet_name="Cover", index=False)
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(w, sheet_name="Data", index=False)
        pd.DataFrame({"b": [9]}).to_excel(w, sheet_name="Other", index=False)
    first = client.post("/api/datasets", files={"file": ("m.xlsx", buf.getvalue())}).json()
    assert first["file"]["sheet"] == "Data" and first["file"]["sheets"] == ["Cover", "Data", "Other"]
    other = client.post("/api/datasets", files={"file": ("m.xlsx", buf.getvalue())}, data={"sheet": "Other"}).json()
    assert other["rows"] == 1 and other["columns"][0]["name"] == "b"
    bad = client.post("/api/datasets", files={"file": ("m.xlsx", buf.getvalue())}, data={"sheet": "Nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_sheet"
