"""P4.1 per-AP load forecasters: a moving-average baseline and Holt's linear-trend smoothing.

Holt-Winters without a seasonal part: each scenario run lasts 10 minutes, so there is no
season to model (decision P4.1-A). Pure Python; the series are short (5 s steps).

    Holt:  L_0 = y_0,  T_0 = y_1 - y_0
           L_t = alpha * y_t + (1 - alpha) * (L_{t-1} + T_{t-1})
           T_t = beta * (L_t - L_{t-1}) + (1 - beta) * T_{t-1}
           forecast(h) = L_n + h * T_n
"""

from __future__ import annotations

from collections.abc import Sequence


def moving_average_forecast(history: Sequence[float], window: int, horizon_steps: int) -> float:
    """Baseline: the mean of the last `window` values, for any horizon.

    `horizon_steps` is unused: it keeps the same signature as holt_forecast, so the evaluation
    treats both forecasters alike."""
    if not history:
        raise ValueError("no history to forecast from")
    recent = history[-window:]
    return sum(recent) / len(recent)


def holt_forecast(history: Sequence[float], alpha: float, beta: float, horizon_steps: int) -> float:
    """Holt's linear trend forecast `horizon_steps` ahead (unclipped)."""
    if not 0 < alpha <= 1:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    if not 0 <= beta <= 1:
        raise ValueError(f"beta must be in [0, 1], got {beta}")
    if not history:
        raise ValueError("no history to forecast from")
    if len(history) == 1:
        return history[0]
    level, trend = history[0], history[1] - history[0]
    for y in history[1:]:
        previous = level
        level = alpha * y + (1 - alpha) * (level + trend)
        trend = beta * (level - previous) + (1 - beta) * trend
    return level + horizon_steps * trend
