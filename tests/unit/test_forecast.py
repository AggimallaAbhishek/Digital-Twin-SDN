"""P4.1 forecasting models and evaluation helpers (ml/forecast/). Expected values worked by hand."""

from __future__ import annotations

import math

import pytest

from ml.forecast.models import holt_forecast, moving_average_forecast
from ml.forecast.series import resample, rmse, rolling_errors


# ------------------------------------------------------------------ moving average (baseline)
def test_moving_average_is_the_mean_of_the_last_window() -> None:
    forecast = moving_average_forecast([0.1, 0.2, 0.6, 0.8], window=2, horizon_steps=12)
    assert forecast == pytest.approx(0.7)


def test_moving_average_with_short_history_uses_what_there_is() -> None:
    assert moving_average_forecast([0.4], window=6, horizon_steps=1) == 0.4


# ------------------------------------------------------------------ Holt (level + trend)
def test_holt_extrapolates_a_straight_line_exactly() -> None:
    # alpha = beta = 0.5 on 1, 2, 3, 4: level 4, trend 1 -> two steps ahead = 6
    forecast = holt_forecast([1.0, 2.0, 3.0, 4.0], alpha=0.5, beta=0.5, horizon_steps=2)
    assert forecast == pytest.approx(6.0)


def test_holt_keeps_a_constant_series_constant() -> None:
    assert holt_forecast([0.5] * 10, alpha=0.3, beta=0.2, horizon_steps=36) == pytest.approx(0.5)


def test_holt_on_a_noisy_series() -> None:
    # init L=1, T=2; y=3: L=0.5*3+0.5*(1+2)=3, T=0.5*(3-1)+0.5*2=2;
    # y=2: L=0.5*2+0.5*(3+2)=3.5, T=0.5*(3.5-3)+0.5*2=1.25 -> h=1: 4.75
    forecast = holt_forecast([1.0, 3.0, 2.0], alpha=0.5, beta=0.5, horizon_steps=1)
    assert forecast == pytest.approx(4.75)


def test_holt_with_one_point_is_flat() -> None:
    assert holt_forecast([0.3], alpha=0.5, beta=0.5, horizon_steps=12) == 0.3


@pytest.mark.parametrize(("alpha", "beta"), [(0.0, 0.5), (1.5, 0.5), (0.5, -0.1), (0.5, 1.1)])
def test_holt_rejects_bad_smoothing(alpha: float, beta: float) -> None:
    with pytest.raises(ValueError, match=r"alpha|beta"):
        holt_forecast([0.1, 0.2], alpha=alpha, beta=beta, horizon_steps=1)


def test_forecasts_need_history() -> None:
    with pytest.raises(ValueError, match="history"):
        holt_forecast([], alpha=0.5, beta=0.5, horizon_steps=1)
    with pytest.raises(ValueError, match="history"):
        moving_average_forecast([], window=3, horizon_steps=1)


# ------------------------------------------------------------------ series
def test_resample_averages_each_bin_and_marks_empty_bins() -> None:
    # bins of 5 s: [0,5) [5,10) [10,15) [15,20)
    points = [(0.5, 0.2), (3.0, 0.4), (6.0, 0.9), (16.0, 0.1)]
    assert resample(points, step_s=5.0) == [pytest.approx(0.3), 0.9, None, 0.1]


def test_resample_of_nothing_is_empty() -> None:
    assert resample([], step_s=5.0) == []


def test_rolling_errors_forecast_each_origin_h_steps_ahead() -> None:
    series = [0.1, 0.2, 0.3, 0.4, 0.5]
    last_value = lambda history: history[-1]  # noqa: E731 - tiny naive forecaster for the test
    # warm-up 2: origins t=1,2 (h=2 needs t+2 <= 4), forecasts 0.2,0.3 vs actual 0.4,0.5
    errors = rolling_errors(series, last_value, horizon_steps=2, warmup_steps=2)
    assert errors == pytest.approx([-0.2, -0.2])


def test_rolling_errors_skip_missing_points() -> None:
    series = [0.1, None, 0.3, None, 0.5]
    errors = rolling_errors(series, lambda h: h[-1], horizon_steps=2, warmup_steps=1)
    # origins t=0 (target t=2: 0.3) and t=2 (target 0.5); t=1, t=3 have no value
    assert errors == pytest.approx([-0.2, -0.2])


def test_rmse() -> None:
    assert rmse([3.0, -4.0]) == pytest.approx(math.sqrt(12.5))
    with pytest.raises(ValueError, match="no errors"):
        rmse([])
