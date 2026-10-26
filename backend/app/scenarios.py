"""What-If simulator: hypothetical, transparent recalculations on the real data.

Rules that keep it honest:
* A change to column X affects metric Y only if X *is* Y, or a formula linking them was
  detected in the data itself (it must hold, within 1%, for at least 98% of complete rows).
  DataLens never assumes a relationship the data doesn't show.
* Scenario values are computed per row as: observed value + change implied by the formula.
  Rows where the formula doesn't hold keep their own deviation, so nothing is smoothed away.
* Results are labelled hypothetical. Nothing models behaviour (e.g. demand reacting to price).
"""

from __future__ import annotations

from itertools import combinations, permutations
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from .investigation import filter_frame, validate_filters
from .operations import OperationError
from .profiling import AMOUNT_HINT
from .utils import fmt_num, fmt_pct, jsonable

FORMULA_TOLERANCE = 0.01
FORMULA_MIN_SHARE = 0.98
MAX_FORMULA_COLUMNS = 10


class Adjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=200)
    percent: float = Field(ge=-90, le=200)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=200)
    agg: Literal["sum", "mean", "median"] = "sum"
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=4)
    exclude: list[dict[str, Any]] = Field(default_factory=list, max_length=4)
    group_by: str | None = None


# ---------------------------------------------------------------- formula detection


def _numeric(df: pd.DataFrame, schema: dict[str, str]) -> list[str]:
    return [c for c, t in schema.items() if t == "numeric" and df[c].nunique() > 1][:MAX_FORMULA_COLUMNS]


def _holds(target: pd.Series, implied: pd.Series) -> tuple[float, int]:
    ok = target.notna() & implied.notna()
    if ok.sum() < 20:
        return 0.0, int(ok.sum())
    t, f = target[ok].astype(float), implied[ok].astype(float)
    close = (t - f).abs() <= FORMULA_TOLERANCE * np.maximum(t.abs(), 1e-9) + 0.01
    return float(close.mean()), int(ok.sum())


DETECTION_SAMPLE = 20_000


def detect_formulas(df: pd.DataFrame, schema: dict[str, str]) -> list[dict[str, Any]]:
    """Find simple arithmetic relationships that hold in the data: T = A×B, T = A×B×(1−C), T = A − B, T = A + B.

    Candidates are searched on a fixed sample (fast on large files); every formula found is then
    re-checked on all rows and kept only if it still holds for ≥ 98% of them.
    """
    full = df
    df = df.sample(n=DETECTION_SAMPLE, random_state=0) if len(df) > DETECTION_SAMPLE else df
    cols = _numeric(full, schema)
    found = []
    num = {c: df[c].astype(float) for c in cols}
    fractions = [c for c in cols if num[c].dropna().between(0, 1).all()]
    for t in cols:
        best = None
        others = [c for c in cols if c != t]
        for a, b in combinations(others, 2):
            share, n = _holds(num[t], num[a] * num[b])
            if share >= FORMULA_MIN_SHARE and (best is None or share > best["holds_share"]):
                best = {"target": t, "kind": "product", "terms": [a, b], "expression": f"{t} = {a} × {b}", "holds_share": share, "rows_checked": n}
            for c in fractions:
                if c in (a, b):
                    continue
                share, n = _holds(num[t], num[a] * num[b] * (1 - num[c]))
                if share >= FORMULA_MIN_SHARE and (best is None or share > best["holds_share"] + 1e-9):
                    best = {"target": t, "kind": "product_discount", "terms": [a, b], "fraction": c,
                            "expression": f"{t} = {a} × {b} × (1 − {c})", "holds_share": share, "rows_checked": n}
        for a, b in permutations(others, 2):
            share, n = _holds(num[t], num[a] - num[b])
            if share >= FORMULA_MIN_SHARE and (best is None or share > best["holds_share"]):
                best = {"target": t, "kind": "difference", "terms": [a, b], "expression": f"{t} = {a} − {b}", "holds_share": share, "rows_checked": n}
        for a, b in combinations(others, 2):
            share, n = _holds(num[t], num[a] + num[b])
            if share >= FORMULA_MIN_SHARE and (best is None or share > best["holds_share"]):
                best = {"target": t, "kind": "sum", "terms": [a, b], "expression": f"{t} = {a} + {b}", "holds_share": share, "rows_checked": n}
        if best:
            share, n = _holds(full[t].astype(float), _evaluate(best, {c: full[c].astype(float) for c in _formula_inputs(best)}))
            if share >= FORMULA_MIN_SHARE:
                best.update(holds_share=round(share, 4), rows_checked=n)
                found.append(best)
    return found


def _formula_inputs(f: dict[str, Any]) -> list[str]:
    return f["terms"] + ([f["fraction"]] if f.get("fraction") else [])


def _evaluate(f: dict[str, Any], cols: dict[str, pd.Series]) -> pd.Series:
    a, b = (cols[t] for t in f["terms"])
    if f["kind"] == "product":
        return a * b
    if f["kind"] == "product_discount":
        return a * b * (1 - cols[f["fraction"]])
    if f["kind"] == "difference":
        return a - b
    return a + b


# ---------------------------------------------------------------- options


def scenario_options(df: pd.DataFrame, schema: dict[str, str]) -> dict[str, Any]:
    formulas = detect_formulas(df, schema)
    numeric = [c for c in _numeric(df, schema)]
    targets = sorted(numeric, key=lambda c: (0 if AMOUNT_HINT.search(c) and any(f["target"] == c for f in formulas) else 1 if AMOUNT_HINT.search(c) else 2))
    adjustable = []
    for c in numeric:
        affects = [c] + [f["target"] for f in formulas if c in _formula_inputs(f)]
        adjustable.append({"column": c, "affects": affects, "fraction": bool(df[c].dropna().between(0, 1).all())})
    groupable = [c for c, t in schema.items() if t in ("categorical", "boolean") and 2 <= df[c].nunique() <= 30]
    suggested = None
    for t in [c for c in numeric if not AMOUNT_HINT.search(c)][:3] + [c for c in numeric if AMOUNT_HINT.search(c)][:1]:
        overall = df[t].mean()
        if pd.isna(overall) or overall == 0:
            continue
        for g in groupable[:6]:
            for value, n in df[g].value_counts().items():
                if n < 10 or n > 0.6 * len(df):
                    continue
                without = df.loc[df[g] != value, t].mean()
                effect = (without - overall) / abs(overall)
                if suggested is None or abs(effect) > abs(suggested["effect"]):
                    suggested = {"target": t, "column": g, "value": jsonable(value), "effect": round(float(effect), 4)}
    return jsonable({
        "suggested_exclusion": suggested,
        "targets": targets,
        "adjustable": adjustable,
        "formulas": formulas,
        "group_columns": groupable,
        "filter_columns": [c for c in schema if schema[c] in ("categorical", "boolean", "numeric", "datetime")],
        "available": bool(numeric),
        "note": "Scenarios are hypothetical recalculations of this data. A change only affects other columns through relationships detected in the data.",
    })


# ---------------------------------------------------------------- run


def run_scenario(df: pd.DataFrame, schema: dict[str, str], req: ScenarioRequest) -> dict[str, Any]:
    errors = []
    lookup = {c.lower(): c for c in schema}
    target = lookup.get(req.target.strip().lower())
    if target is None or schema[target] != "numeric":
        raise OperationError([f"'{req.target}' isn't a number column, so it can't be a scenario target."])
    adj_cols = []
    for a in req.adjustments:
        c = lookup.get(a.column.strip().lower())
        if c is None:
            errors.append(f"There is no column called '{a.column}'.")
        elif schema[c] != "numeric":
            errors.append(f"{c} is {schema[c]}; only number columns can be adjusted.")
        else:
            adj_cols.append((c, a.percent))
    if len({c for c, _ in adj_cols}) != len(adj_cols):
        errors.append("Adjust each column at most once.")
    group_by = None
    if req.group_by:
        group_by = lookup.get(req.group_by.strip().lower())
        if group_by is None or schema[group_by] not in ("categorical", "boolean"):
            errors.append(f"'{req.group_by}' can't be used to break down results; pick a category column.")
    exclude = []
    try:
        exclude = validate_filters(req.exclude, df, schema)
    except OperationError as exc:
        errors += exc.errors
    if errors:
        raise OperationError(errors)
    if not adj_cols and not exclude:
        raise OperationError(["Add at least one adjustment or exclusion to build a scenario."])

    formulas = {f["target"]: f for f in detect_formulas(df, schema)}
    formula = formulas.get(target)
    assumptions = [
        "Hypothetical recalculation of the observed data. It doesn't predict the future or model behaviour (for example, customers reacting to a price change).",
        "Everything not adjusted stays exactly as observed.",
    ]
    steps = []
    warnings = []
    effective = []
    for c, pct in adj_cols:
        if c == target:
            effective.append((c, pct, "direct"))
        elif formula and c in _formula_inputs(formula):
            effective.append((c, pct, "formula"))
        else:
            warnings.append(f"Changing {c} doesn't affect {target}: no relationship between them was detected in the data, and DataLens won't assume one.")
    if not effective and not exclude:
        raise OperationError([w for w in warnings] or ["None of these changes affect the target."])
    if any(kind == "direct" for _, _, kind in effective) and any(kind == "formula" for _, _, kind in effective):
        raise OperationError([f"Adjust either {target} itself or the columns it's calculated from, not both, so the effect isn't counted twice."])

    base = df.copy()
    observed_total = len(base)
    scen = base
    if exclude:
        scen = base.loc[~base.index.isin(filter_frame(base, exclude, schema).index)]
        removed = observed_total - len(scen)
        if len(scen) == 0:
            raise OperationError(["These exclusions remove every row, so there's nothing left to calculate."])
        steps.append(f"Excluded {fmt_num(removed)} of {fmt_num(observed_total)} rows matching the exclusion filters.")
    scen_target = scen[target].astype(float).copy()
    if formula and any(kind == "formula" for _, _, kind in effective):
        inputs = {c: scen[c].astype(float) for c in _formula_inputs(formula)}
        adjusted = dict(inputs)
        for c, pct, kind in effective:
            if kind != "formula":
                continue
            if formula.get("fraction") == c:
                adjusted[c] = (inputs[c] * (1 + pct / 100)).clip(0, 1)
                steps.append(f"Scaled {c} by {fmt_pct(pct)}, capped to the 0–1 range.")
            else:
                adjusted[c] = inputs[c] * (1 + pct / 100)
                steps.append(f"Scaled {c} by {fmt_pct(pct)}.")
        before, after = _evaluate(formula, inputs), _evaluate(formula, adjusted)
        if formula["kind"] in ("product", "product_discount"):
            # Multiplicative: scale each observed value by the formula's ratio. This keeps refunds negative,
            # special prices special, and gives exactly +5% revenue for +5% price.
            ratio = (after / before).where(before != 0)
            scen_target = scen_target * ratio.fillna(1.0)
            how = f"each row's observed {target} × (formula after change ÷ formula before change)"
        else:
            scen_target = scen_target + (after - before).fillna(0)
            how = f"each row's observed {target} + (formula after change − formula before change)"
        steps.append(f"Recomputed {target} with the detected formula {formula['expression']} (holds for {formula['holds_share'] * 100:.1f}% of "
                     f"{fmt_num(formula['rows_checked'])} rows): {how}.")
        assumptions.append(f"Uses the relationship {formula['expression']}, found in the data itself. Rows where it doesn't hold exactly keep their own observed value as the starting point.")
    for c, pct, kind in effective:
        if kind == "direct":
            scen_target = scen_target * (1 + pct / 100)
            steps.append(f"Scaled {target} by {fmt_pct(pct)} on every row.")

    def agg(s: pd.Series) -> float:
        s = s.dropna()
        return float(getattr(s, req.agg)()) if len(s) else float("nan")

    baseline_value = agg(base[target].astype(float))
    scenario_value = agg(scen_target)
    change = scenario_value - baseline_value
    pct_change = change / abs(baseline_value) * 100 if baseline_value else None
    missing = int(base[target].isna().sum())
    if missing:
        warnings.append(f"{fmt_num(missing)} rows have no {target} and are left out of both the baseline and the scenario.")
    steps.append(f"Baseline = {req.agg} of observed {target} over {fmt_num(observed_total)} rows; scenario = {req.agg} of the recalculated values over {fmt_num(len(scen))} rows.")

    breakdown = []
    if group_by:
        b_groups = base.groupby(group_by, observed=True)[target].agg(req.agg)
        s_groups = scen_target.groupby(scen[group_by], observed=True).agg(req.agg)
        for g in b_groups.index:
            bv = float(b_groups.get(g, np.nan))
            sv = float(s_groups.get(g, np.nan)) if g in s_groups.index else float("nan")
            breakdown.append({group_by: str(g), "baseline": jsonable(bv), "scenario": jsonable(sv),
                              "change": jsonable(sv - bv), "% change": jsonable(round((sv - bv) / abs(bv) * 100, 2) if bv else None)})
        breakdown.sort(key=lambda r: -(abs(r["change"]) if r["change"] is not None else 0))

    label = f"{ {'sum': 'total', 'mean': 'average', 'median': 'median'}[req.agg]} {target}".strip()
    return jsonable({
        "kind": "scenario",
        "hypothetical": True,
        "target": target,
        "agg": req.agg,
        "label": label,
        "baseline": baseline_value,
        "scenario": scenario_value,
        "change": change,
        "pct_change": pct_change,
        "summary": f"In this hypothetical scenario the {label} would be {fmt_num(scenario_value)} instead of the observed {fmt_num(baseline_value)} "
        f"({'+' if change >= 0 else ''}{fmt_num(change)}{f', {fmt_pct(pct_change)}' if pct_change is not None else ''}).",
        "rows_baseline": observed_total,
        "rows_scenario": int(len(scen)),
        "formula": formula,
        "steps": steps,
        "assumptions": assumptions,
        "warnings": warnings,
        "group_by": group_by,
        "breakdown": breakdown[:12],
        "chart": {"type": "bar", "x": group_by, "series": ["baseline", "scenario"], "data": [{group_by: r[group_by], "baseline": r["baseline"], "scenario": r["scenario"]} for r in breakdown[:12]]}
        if group_by else {"type": "bar", "x": "case", "series": [label], "data": [{"case": "Observed", label: baseline_value}, {"case": "Scenario", label: scenario_value}]},
    })
