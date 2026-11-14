"""Small statistics helpers: t-intervals for means and paired contrasts.

The experiments pair arms by replication seed (common random numbers),
so the headline contrasts are per-seed differences with a paired
t-interval. The LLM check makes one call per configuration, so its
accuracy intervals are Wilson score intervals. See DECISIONS.md for
why P01's ``errorbars`` module (built for accuracy-over-questions
tables) is not the right estimand here.
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def mean_ci(values, level: float = 0.95) -> tuple[float, float, float]:
    """(mean, lower, upper) t-interval for a sample mean."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    m = float(x.mean())
    if n < 2:
        return m, float("nan"), float("nan")
    se = float(x.std(ddof=1)) / np.sqrt(n)
    crit = float(stats.t.ppf(0.5 + level / 2.0, n - 1))
    return m, m - crit * se, m + crit * se


def paired_diff_ci(a, b, level: float = 0.95) -> tuple[float, float, float]:
    """(mean, lower, upper) for the paired difference a - b."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return mean_ci(d, level)


def wilson_ci(k: int, n: int, level: float = 0.95) -> tuple[float, float, float]:
    """(proportion, lower, upper) Wilson score interval."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    z = float(stats.norm.ppf(0.5 + level / 2.0))
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)
