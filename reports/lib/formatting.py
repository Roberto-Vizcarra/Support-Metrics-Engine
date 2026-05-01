"""Display formatting helpers.

Per docs/02 § 7:
  - Milliseconds: hours if < 48h, days if 2–60 days, months if > 60d
  - Counts: integer with thousands separator
  - Ratings: 1 decimal place
  - Percentages: 1 or 2 decimals
"""

from __future__ import annotations

import statistics
from typing import Iterable


def format_duration_ms(ms: float | int | None) -> str:
    if ms is None:
        return "—"
    if ms < 0:
        return "—"
    hours = ms / 3_600_000
    days = hours / 24
    if hours < 48:
        return f"{hours:.1f}h"
    if days < 60:
        return f"{days:.1f}d"
    return f"{days/30:.1f}mo"


def format_count(n: int) -> str:
    return f"{n:,}"


def format_pct(n: float, decimals: int = 1) -> str:
    return f"{n:.{decimals}f}%"


def format_rating(r: float | None) -> str:
    if r is None:
        return "—"
    return f"{r:.1f}"


def median(values: Iterable[float | int]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.median(vals)


def mean(values: Iterable[float | int]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.fmean(vals)


def percentile(values: Iterable[float | int], p: float) -> float | None:
    """p in [0,100]. Linear interpolation."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(vals) - 1)
    if f == c:
        return vals[f]
    return vals[f] + (vals[c] - vals[f]) * (k - f)
