"""P4.2 anomaly metrics (ml/anomaly/metrics.py) and detector (ml/anomaly/detector.py)."""

from __future__ import annotations

import numpy as np
import pytest

from ml.anomaly.detector import Detector
from ml.anomaly.metrics import best_threshold, detection_delays, prf

NAMES = ["ap1.util_mean", "ap1.silent", "ap2.util_mean", "ap2.silent", "net.loss_mean"]


# ------------------------------------------------------------------ metrics
def test_precision_recall_f1() -> None:
    labels = [True, True, False, False, True]
    flags = [True, False, True, False, True]  # TP 2, FP 1, FN 1
    p, r, f1 = prf(labels, flags)
    assert p == pytest.approx(2 / 3)
    assert r == pytest.approx(2 / 3)
    assert f1 == pytest.approx(2 / 3)


def test_metrics_with_nothing_flagged_are_zero_not_an_error() -> None:
    assert prf([True, False], [False, False]) == (0.0, 0.0, 0.0)


def test_best_threshold_maximises_f1() -> None:
    scores = [0.1, 0.2, 0.8, 0.9, 0.3]
    labels = [False, False, True, True, False]
    assert best_threshold(scores, labels) == 0.8  # flag >= 0.8: F1 = 1


def test_best_threshold_needs_scores() -> None:
    with pytest.raises(ValueError, match="no scores"):
        best_threshold([], [])


def test_detection_delay_is_first_alert_at_or_after_onset() -> None:
    # (run, onset, t_end, flagged)
    rows = [
        ("ap_failure-s44", 240.0, 235.0, True),  # before onset: a false alarm
        ("ap_failure-s44", 240.0, 240.0, False),
        ("ap_failure-s44", 240.0, 250.0, True),  # detected 10 s after onset
        ("cochannel-s44", 180.0, 200.0, False),  # never detected
        ("normal-s44", None, 100.0, True),  # normal run: false alarm, no onset
    ]
    assert detection_delays(rows) == {
        "ap_failure-s44": {"delay_s": 10.0, "false_alarms_before": 1},
        "cochannel-s44": {"delay_s": None, "false_alarms_before": 0},
    }


# ------------------------------------------------------------------ detector
def _normal(n: int, rng: np.random.Generator) -> list[list[float]]:
    """Normal windows: both APs ~30% busy and reporting, ~1% loss."""
    util = rng.normal(0.3, 0.05, size=(n, 2))
    loss = rng.normal(1.0, 0.2, size=n)
    return [
        [float(u1), 0.0, float(u2), 0.0, float(lo)] for (u1, u2), lo in zip(util, loss, strict=True)
    ]


def test_unusual_windows_score_higher() -> None:
    rng = np.random.default_rng(7)
    detector = Detector.fit(_normal(300, rng), NAMES, seed=42, n_estimators=100)
    normal, odd = _normal(1, rng)[0], [0.3, 1.0, 0.95, 0.0, 9.0]  # ap1 silent, ap2 saturated
    s_normal, s_odd = detector.score([normal, odd])
    assert s_odd > s_normal


def test_scores_are_reproducible_with_the_same_seed() -> None:
    data = _normal(200, np.random.default_rng(1))
    a = Detector.fit(data, NAMES, seed=42, n_estimators=50).score(data[:5])
    b = Detector.fit(data, NAMES, seed=42, n_estimators=50).score(data[:5])
    assert a == b


def test_alert_names_the_ap_that_deviates_most() -> None:
    detector = Detector.fit(_normal(300, np.random.default_rng(3)), NAMES, seed=42, n_estimators=50)
    assert detector.entity([0.3, 0.0, 0.3, 1.0, 1.0]) == "ap2"  # ap2 silent
    assert detector.entity([0.9, 0.0, 0.3, 0.0, 1.0]) == "ap1"  # ap1 utilisation far up


def test_network_wide_deviation_names_the_network() -> None:
    detector = Detector.fit(_normal(300, np.random.default_rng(3)), NAMES, seed=42, n_estimators=50)
    assert detector.entity([0.3, 0.0, 0.3, 0.0, 9.0]) == "network"  # only loss is off
