"""The accuracy benchmark doubles as a regression guard: any change that breaks a calculation fails here."""
from app import benchmark


def test_every_calculation_case_passes(client):
    r = client.post("/api/benchmark/run", json={}).json()
    calc = r["tracks"]["calculation"]
    failures = [(x["id"], x["calculation"]["explanation"]) for x in r["results"] if "calculation" in x and x["calculation"]["status"] != "pass"]
    assert not failures, failures
    assert calc["total"] == 32 and calc["pass"] == 32 and calc["accuracy"] == 100.0
    assert r["tracks"]["visualization"]["fail"] == 0
    assert all(d["ok"] for d in r["datasets"].values())


def test_ai_track_is_skipped_without_a_key(client):
    r = client.post("/api/benchmark/run", json={"include_ai": True}).json()
    assert r["tracks"]["interpretation"]["skipped"] == r["tracks"]["interpretation"]["total"] > 0
    assert r["tracks"]["interpretation"]["accuracy"] is None  # never invents a score


def test_comparison_detects_wrong_answers():
    assert benchmark._compare(101.0, {"kind": "number", "value": 100.0, "rel_tol": 0, "abs_tol": 0.5})[0] is False
    assert benchmark._compare({"a": 1.0}, {"kind": "table", "value": {"a": 1.0, "b": 2.0}})[0] is False
    assert benchmark._compare("West", {"kind": "text", "value": "East"})[0] is False


def test_changed_dataset_is_detected(monkeypatch, tmp_path):
    suite = benchmark.load_suite()
    suite["datasets"]["edge"]["sha256"] = "0" * 64
    monkeypatch.setattr(benchmark, "load_suite", lambda: suite)
    r = benchmark.run_suite()
    edge = [x for x in r["results"] if x["dataset"] == "edge"]
    assert all(x["calculation"]["status"] == "error" and "benchmark version" in x["calculation"]["explanation"] for x in edge)


def test_single_case_rerun(client):
    r = client.post("/api/benchmark/run", json={"ids": ["R12"]}).json()
    assert [x["id"] for x in r["results"]] == ["R12"] and r["results"][0]["calculation"]["status"] == "pass"


def test_dashboard_runs_do_not_fill_history(client):
    ds = client.post("/api/datasets/sample").json()
    client.post(f"/api/datasets/{ds['id']}/run", json={"operation": {"type": "aggregate", "agg": "count"}, "record": False})
    assert "Custom analysis" not in client.get(f"/api/datasets/{ds['id']}/report").text
