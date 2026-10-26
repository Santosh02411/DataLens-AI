"""Small, dependency-free statistics used by insight discovery.

Implements the distribution tails needed for the tests below (normal, chi-square,
Student t) plus Kruskal-Wallis, Mann-Kendall with Sen's slope, Pearson's r test
and a chi-square test of independence. The special functions follow the standard
series / continued-fraction formulations (Numerical Recipes, 3rd ed., ch. 6) and
are checked against SciPy in the test suite's reference values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

_EPS = 1e-15
_FPMIN = 1e-300


# ---------------------------------------------------------------- special functions


def _gammainc_lower_series(a: float, x: float) -> float:
    term = total = 1.0 / a
    ap = a
    for _ in range(1000):
        ap += 1
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammainc_upper_cf(a: float, x: float) -> float:
    b = x + 1 - a
    c = 1 / _FPMIN
    d = 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = _FPMIN if abs(d) < _FPMIN else d
        c = b + an / c
        c = _FPMIN if abs(c) < _FPMIN else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        return max(0.0, 1.0 - _gammainc_lower_series(a, x))
    return min(1.0, _gammainc_upper_cf(a, x))


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = _FPMIN if abs(d) < _FPMIN else d
    d = 1 / d
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = _FPMIN if abs(d) < _FPMIN else d
        c = 1 + aa / c
        c = _FPMIN if abs(c) < _FPMIN else c
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = _FPMIN if abs(d) < _FPMIN else d
        c = 1 + aa / c
        c = _FPMIN if abs(c) < _FPMIN else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(ln_front)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def chi2_sf(x: float, df: float) -> float:
    return gammaincc(df / 2, x / 2)


def t_sf_two_sided(t: float, df: float) -> float:
    return betainc(df / 2, 0.5, df / (df + t * t))


# ---------------------------------------------------------------- tests


@dataclass
class KruskalResult:
    h: float
    p: float
    epsilon_sq: float
    n: int
    k: int


def kruskal_wallis(values: pd.Series, groups: pd.Series) -> KruskalResult | None:
    """Kruskal-Wallis H test with tie correction. Effect size: epsilon² = H / (n - 1)."""
    frame = pd.DataFrame({"v": values.astype(float), "g": groups}).dropna()
    n = len(frame)
    k = frame["g"].nunique()
    if k < 2 or n < k + 2:
        return None
    ranks = frame["v"].rank(method="average")
    rank_sums = ranks.groupby(frame["g"], observed=True).sum()
    sizes = frame.groupby("g", observed=True).size()
    h = 12 / (n * (n + 1)) * float((rank_sums**2 / sizes).sum()) - 3 * (n + 1)
    ties = frame["v"].value_counts()
    correction = 1 - float((ties**3 - ties).sum()) / (n**3 - n)
    if correction <= 0:
        return None
    h /= correction
    return KruskalResult(h=h, p=chi2_sf(h, k - 1), epsilon_sq=max(0.0, h / (n - 1)), n=n, k=k)


@dataclass
class TrendResult:
    s: int
    z: float
    p: float
    tau: float
    slope: float
    n: int


def mann_kendall(y: list[float] | np.ndarray) -> TrendResult | None:
    """Mann-Kendall monotonic trend test (normal approximation, tie-corrected) with Sen's slope."""
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    n = len(y)
    if n < 4:
        return None
    diff = np.sign(y[None, :] - y[:, None])
    s = int(np.triu(diff, 1).sum())
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - float((counts * (counts - 1) * (2 * counts + 5)).sum())) / 18
    if var <= 0:
        return None
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    i, j = np.triu_indices(n, 1)
    slope = float(np.median((y[j] - y[i]) / (j - i)))
    tau = s / (n * (n - 1) / 2)
    return TrendResult(s=s, z=z, p=2 * norm_sf(abs(z)), tau=tau, slope=slope, n=n)


def spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman's rank correlation: Pearson correlation of average ranks.

    Implemented here because pandas' method="spearman" needs SciPy, which DataLens doesn't depend on.
    """
    return float(x.rank(method="average").corr(y.rank(method="average")))


def pearson_p(r: float, n: int) -> float:
    if n < 4 or abs(r) >= 1:
        return 0.0 if abs(r) >= 1 else 1.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return t_sf_two_sided(t, n - 2)


def chi2_independence(table: np.ndarray) -> tuple[float, float, int] | None:
    """Pearson chi-square test of independence for an r×c count table. Returns (chi2, p, dof)."""
    table = np.asarray(table, dtype=float)
    table = table[table.sum(axis=1) > 0][:, table.sum(axis=0) > 0]
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    expected = table.sum(axis=1, keepdims=True) * table.sum(axis=0, keepdims=True) / table.sum()
    if (expected < 1).any():
        return None
    chi2 = float(((table - expected) ** 2 / expected).sum())
    dof = (table.shape[0] - 1) * (table.shape[1] - 1)
    return chi2, chi2_sf(chi2, dof), dof


def fmt_p(p: float) -> str:
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"
