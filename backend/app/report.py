"""Downloadable Markdown report built only from computed profile and analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .store import Dataset
from .utils import fmt_value


def _cell(v: Any) -> str:
    return fmt_value(v).replace("|", "\\|").replace("\n", " ")


def _table(columns: list[str], rows: list[dict[str, Any]], limit: int = 15) -> list[str]:
    if not columns or not rows:
        return []
    out = ["| " + " | ".join(_cell(c) for c in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for r in rows[:limit]:
        out.append("| " + " | ".join(_cell(r.get(c)) for c in columns) + " |")
    if len(rows) > limit:
        out.append(f"\n_{len(rows) - limit} more rows not shown._")
    return out


def build_report(ds: Dataset) -> str:
    p = ds.profile
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# DataLens AI report: {ds.name}",
        "",
        f"Generated {now}. Every figure in this report was computed from the uploaded data with Pandas.",
        "",
        "## Dataset overview",
        "",
        f"- Rows: {p['rows']:,}",
        f"- Columns: {p['columns']}",
        f"- Data quality score: {p['quality_score']}/100 ({p['quality_formula']})",
        f"- Missing cells: {p['missing_cells']:,} ({p['missing_pct']}%)",
        f"- Duplicate rows: {p['duplicate_rows']:,} ({p['duplicate_pct']}%)",
        "",
        "## Data health issues",
        "",
    ]
    if p["issues"]:
        for i in p["issues"]:
            lines.append(f"- **{i['severity'].capitalize()}**: {i['title']}. {i['detail']}")
    else:
        lines.append("No issues found.")
    lines += ["", "## Columns", ""]
    col_rows = [
        {"Column": c["name"], "Type": c["type"], "Missing": f"{c['missing']:,} ({c['missing_pct']}%)", "Distinct": f"{c['unique']:,}"}
        for c in p["column_profiles"]
    ]
    lines += _table(["Column", "Type", "Missing", "Distinct"], col_rows, limit=200)

    lines += ["", "## Automatically discovered insights", ""]
    found = (ds.insights or {}).get("insights", [])
    if not found:
        lines.append("No findings passed the evidence thresholds.")
    for n, ins in enumerate(found, 1):
        level = {"strong": "Strong evidence", "moderate": "Moderate evidence", "notable": "Worth a look", "data_quality": "Data quality", "info": "For information"}[ins["level"]]
        lines += [f"### {n}. {ins['title']}", "", f"_{ins['kind_label']} · {level}_", "", ins["finding"], ""]
        lines += ["| Statistic | Value |", "| --- | --- |"] + [f"| {_cell(st['label'])} | {_cell(st['value'])} |" for st in ins["stats"]] + [""]
        lines += [f"Method: {ins['method']}", ""]
        lines += [f"- Caveat: {c}" for c in ins.get("caveats", [])] + [""]
        if ins["id"] in ds.explanations:
            lines += [f"AI-written explanation (wording only; numbers checked against the statistics above): {ds.explanations[ins['id']]}", ""]
    lines += ["", "## Analyses", ""]
    if not ds.history:
        lines.append("No questions were asked in this session.")
    for n, h in enumerate(ds.history, 1):
        lines += [f"### {n}. {h['question']}", ""]
        if h.get("intent") and h["intent"] != h["question"]:
            lines += [f"_Interpreted as: {h['intent']}_", ""]
        r = h["result"]
        lines += [f"**Answer:** {r['answer']}", ""]
        if r.get("steps"):
            lines += ["How it was computed:", ""] + [f"{i}. {s}" for i, s in enumerate(r["steps"], 1)] + [""]
        if r.get("warnings"):
            lines += ["Warnings:", ""] + [f"- {w}" for w in r["warnings"]] + [""]
        res = r.get("result")
        if res and res.get("rows"):
            lines += _table(res["columns"], res["rows"]) + [""]
    return "\n".join(lines) + "\n"
