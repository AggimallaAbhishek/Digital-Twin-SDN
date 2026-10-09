"""P4.5 time to recover (experiments/analysis/time_to_recover.py), problem statement §5.1."""

from __future__ import annotations

from typing import Any

import pytest

from experiments.analysis.time_to_recover import RecoveryRule, affected_ap, time_to_recover

RULE = RecoveryRule(util_limit=0.8, video_latency_ms=50.0, hold_s=15.0)


def _aps(util_of: dict[str, list[float]]) -> list[dict[str, Any]]:
    return [
        {"t_s": float(t), "ap": ap, "channel_util": u}
        for ap, series in util_of.items()
        for t, u in enumerate(series)
    ]


def _videos(latencies: list[float]) -> list[dict[str, Any]]:
    return [
        {"t_s": float(t), "app_class": "video", "latency_ms": lat}
        for t, lat in enumerate(latencies)
    ]


def test_the_affected_ap_is_the_busiest_right_after_onset() -> None:
    rows = _aps({"ap1": [0.3] * 10 + [0.95] * 20, "ap2": [0.5] * 30})
    assert affected_ap(rows, onset_s=10, window_s=20) == "ap1"


def test_recovery_needs_both_conditions_to_hold_for_the_hold_time() -> None:
    # ap1 congested from t = 10 to 39, back under 80% from 40; video latency fine throughout
    util = [0.3] * 10 + [0.95] * 30 + [0.6] * 40
    ttr = time_to_recover(_aps({"ap1": util}), _videos([10.0] * 80), "ap1", 10, RULE)
    assert ttr == 30.0


def test_a_short_dip_under_the_limit_is_not_recovery() -> None:
    util = [0.95] * 20 + [0.7] * 5 + [0.95] * 10 + [0.6] * 40  # dips at 20-24, recovers at 35
    ttr = time_to_recover(_aps({"ap1": util}), _videos([10.0] * 75), "ap1", 0, RULE)
    assert ttr == 35.0


def test_video_latency_over_the_objective_delays_recovery() -> None:
    util = [0.95] * 10 + [0.6] * 60
    latency = [80.0] * 25 + [20.0] * 45  # latency fine only from t = 25
    ttr = time_to_recover(_aps({"ap1": util}), _videos(latency), "ap1", 0, RULE)
    assert ttr == 25.0


def test_no_recovery_before_the_data_ends_is_none() -> None:
    util = [0.95] * 60
    assert time_to_recover(_aps({"ap1": util}), _videos([10.0] * 60), "ap1", 0, RULE) is None


def test_a_second_without_video_samples_counts_as_meeting_the_objective() -> None:
    util = [0.95] * 5 + [0.6] * 30
    assert time_to_recover(_aps({"ap1": util}), [], "ap1", 0, RULE) == 5.0


@pytest.mark.parametrize("bad", [{"util_limit": 0}, {"hold_s": -1}, {"video_latency_ms": 0}])
def test_a_bad_rule_is_refused(bad: dict[str, float]) -> None:
    raw = {"util_limit": 0.8, "video_latency_ms": 50.0, "hold_s": 15.0} | bad
    with pytest.raises(ValueError, match=next(iter(bad))):
        RecoveryRule(**raw)


def test_other_aps_and_other_traffic_are_ignored() -> None:
    rows = _aps({"ap1": [0.95] * 5 + [0.6] * 30, "ap2": [0.99] * 35})
    web = [{"t_s": float(t), "app_class": "web", "latency_ms": 500.0} for t in range(35)]
    assert time_to_recover(rows, web, "ap1", 0, RULE) == 5.0
    assert time_to_recover(rows, web, "ap9", 0, RULE) is None  # no stats for that AP
