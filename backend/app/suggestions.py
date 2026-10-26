"""Suggested questions, generated from the dataset's real schema.

Each suggestion carries a ready-made operation, so it can run even when no AI
provider is configured. When AI is configured the question text is sent
through the interpreter like any typed question.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

import pandas as pd

from .profiling import AMOUNT_HINT

GROUP_HINT = re.compile(r"region|country|state|city|market|segment|department|team|store", re.I)
MISSING_CONCEPTS = ["profit", "customer age", "marketing spend", "employee count", "temperature"]


PRIORITY = [re.compile(p, re.I) for p in (r"revenue|sales|amount|total", r"price|cost|value|spend", r"qty|quantity|units|count")]


def _pick(cols: list[str]) -> str | None:
    if not cols:
        return None
    for pattern in PRIORITY:
        for c in cols:
            if pattern.search(c):
                return c
    return cols[0]


def build_suggestions(df: pd.DataFrame, schema: dict[str, str]) -> list[dict[str, Any]]:
    nums = [c for c, t in schema.items() if t == "numeric" and df[c].nunique() > 1]
    cats = sorted(
        [c for c, t in schema.items() if t == "categorical" and 2 <= df[c].nunique() <= 30],
        key=lambda c: df[c].nunique(),
    )
    dates = [c for c, t in schema.items() if t == "datetime"]
    num = _pick(nums)
    cats.sort(key=lambda c: 0 if GROUP_HINT.search(c) else 1)
    cat = cats[0] if cats else None
    date = dates[0] if dates else None
    out: list[dict[str, Any]] = []

    if num and cat:
        out.append({
            "question": f"Which {cat} has the highest total {num}?",
            "kind": "Compare groups",
            "operation": {"type": "aggregate", "agg": "sum", "column": num, "group_by": [cat], "sort": "desc", "limit": 15},
        })

    if date and num and cats:
        best = None  # (pct_drop, cat, period_a, period_b)
        for c in cats[:5]:
            q = df[[date, c, num]].dropna()
            if q.empty:
                continue
            q = q.assign(_q=q[date].dt.to_period("Q"))
            pivot = q.pivot_table(index=c, columns="_q", values=num, aggfunc="sum", observed=True).sort_index(axis=1)
            for a, b in zip(pivot.columns[:-1], pivot.columns[1:]):
                base = pivot[a].where(pivot[a] > 0)
                pct = ((pivot[b] - pivot[a]) / base).min()
                if pd.notna(pct) and pct < 0 and (best is None or pct < best[0]):
                    best = (pct, c, a, b)
        if best:
            _, c, a, b = best
            pa, pb = f"{a.year}-Q{a.quarter}", f"{b.year}-Q{b.quarter}"
            out.append({
                "question": f"Which {c}'s total {num} dropped the most from {pa} to {pb}?",
                "kind": "Find a change",
                "operation": {"type": "period_change", "date_column": date, "agg": "sum", "value_column": num, "granularity": "quarter", "period_a": pa, "period_b": pb, "group_by": c, "sort": "asc"},
            })

    if date and num:
        out.append({
            "question": f"How did total {num} change month by month?",
            "kind": "Trend",
            "operation": {"type": "trend", "date_column": date, "agg": "sum", "value_column": num, "granularity": "month"},
        })

    pairs = []
    for a, b in combinations(nums[:10], 2):
        if AMOUNT_HINT.search(a) and AMOUNT_HINT.search(b):
            continue
        sub = df[[a, b]].dropna()
        if len(sub) < 10 or sub[a].nunique() < 2 or sub[b].nunique() < 2:
            continue
        r = sub[a].astype(float).corr(sub[b].astype(float))
        if pd.notna(r) and abs(r) < 0.98:
            pairs.append((abs(r), a, b))
    if pairs:
        _, a, b = max(pairs)
        out.append({
            "question": f"Is {b} related to {a}?",
            "kind": "Relationship",
            "operation": {"type": "correlation", "column_x": a, "column_y": b, "method": "pearson"},
        })

    if num:
        out.append({
            "question": f"Which 10 rows have the highest {num}?",
            "kind": "Top rows",
            "operation": {"type": "top_rows", "sort_by": num, "order": "desc", "n": 10},
        })
        out.append({
            "question": f"How are {num} values distributed?",
            "kind": "Distribution",
            "operation": {"type": "distribution", "column": num, "bins": 20},
        })

    lowered = " ".join(schema).lower()
    concept = next((c for c in MISSING_CONCEPTS if c.split()[0] not in lowered and c.split()[-1] not in lowered), None)
    if concept:
        by = f" by {cat}" if cat else ""
        out.append({
            "question": f"What is the average {concept}{by}?",
            "kind": "Honesty check",
            "operation": {
                "type": "unanswerable",
                "reason": f"This dataset has no column for {concept}, so it can't be calculated. Available columns: {', '.join(list(schema)[:12])}.",
                "missing": [concept],
            },
        })
    return out
