"""P4.1 series helpers: resample telemetry to fixed steps, rolling-origin errors, RMSE."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

Forecaster = Callable[[Sequence[float]], float]


def resample(points: Sequence[tuple[float, float]], step_s: float) -> list[float | None]:
    """Mean of the values in each `step_s` bin [i*step, (i+1)*step); None for empty bins."""
    if not points:
        return []
    bins: dict[int, list[float]] = {}
    for t_s, value in points:
        bins.setdefault(int(t_s // step_s), []).append(value)
    return [sum(bins[i]) / len(bins[i]) if i in bins else None for i in range(max(bins) + 1)]


def rolling_errors(
    series: Sequence[float | None],
    forecast: Forecaster,
    horizon_steps: int,
    warmup_steps: int,
) -> list[float]:
    """Forecast minus actual, from every origin t that has a value, at least `warmup_steps`
    values of history and a value at t + horizon (rolling-origin evaluation)."""
    errors = []
    history: list[float] = []
    for t, value in enumerate(series[: len(series) - horizon_steps]):
        if value is None:
            continue
        history.append(value)
        actual = series[t + horizon_steps]
        if len(history) >= warmup_steps and actual is not None:
            errors.append(forecast(history) - actual)
    return errors


def rmse(errors: Sequence[float]) -> float:
    """Root mean square error."""
    if not errors:
        raise ValueError("no errors to score")
    return math.sqrt(sum(e * e for e in errors) / len(errors))
