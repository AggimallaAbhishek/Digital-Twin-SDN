"""P4.2 / P5.6 detector training from a dataset (ml/anomaly/training.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ml.anomaly.detector import Detector
from ml.anomaly.features import feature_names, windows
from ml.anomaly.training import fit_from_runs, load_runs, normal_windows

APS = ["ap1", "ap2"]


def _write(
    dataset: Path, runs: dict[str, tuple[str, str, float | None]], seconds: int = 90
) -> None:
    """One parquet per measurement; `runs` = run_id -> (scenario, split, stress onset or None)."""
    ap, sta, kpi = [], [], []
    for run_id, (scenario, split, onset) in runs.items():
        for t in range(seconds):
            phase = "stress" if onset is not None and t >= onset else "normal"
            base: dict[str, Any] = {
                "run_id": run_id,
                "scenario_id": scenario,
                "split": split,
                "t_s": float(t),
                "phase": phase,
            }
            stress = phase == "stress"  # a flash crowd: busy AP, more clients, slow and lossy
            util = 0.99 if stress else 0.3 + 0.01 * (t % 7)
            clients = 9 if stress else 3
            ap += [base | {"ap": a, "channel_util": util, "n_clients": clients} for a in APS]
            sta.append(base | {"sta": "sta1", "ap": "ap1"})
            kpi.append(
                base | {"loss_pct": 20.0 if stress else 0.1, "latency_ms": 80.0 if stress else 5.0}
            )
    dataset.mkdir(parents=True, exist_ok=True)
    for name, rows in (("ap_stats", ap), ("sta_stats", sta), ("kpi", kpi)):
        pq.write_table(pa.Table.from_pylist(rows), dataset / f"{name}.parquet")


def test_runs_get_their_onset_from_the_stress_label(tmp_path: Path) -> None:
    _write(
        tmp_path, {"flash-s42": ("flash", "train", 60.0), "normal-s42": ("normal", "train", None)}
    )
    runs = {r.run_id: r for r in load_runs(tmp_path)}
    assert runs["flash-s42"].onset_s == 60.0
    assert runs["normal-s42"].onset_s is None
    assert (runs["flash-s42"].scenario_id, runs["flash-s42"].split) == ("flash", "train")


def test_only_the_train_splits_windows_before_any_stress_are_normal(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"flash-s42": ("flash", "train", 60.0), "normal-s43": ("normal", "val", None)},
    )
    windows = normal_windows(load_runs(tmp_path), APS, step_s=5, window_s=30)
    # flash-s42: windows end at 30, 35, ..., 60 (the one ending at 60 holds no stress yet)
    assert len(windows) == 7
    assert all(len(w) == 2 * 5 + 3 for w in windows)  # 5 features per AP + 3 network ones


def test_the_detector_is_fitted_on_exactly_the_normal_train_windows(tmp_path: Path) -> None:
    # detection quality is measured on real data by experiments/analysis/anomaly_eval.py (P4.2);
    # here: the training plumbing gives the same detector as fitting those windows directly
    _write(
        tmp_path, {"normal-s42": ("normal", "train", None), "flash-s42": ("flash", "train", 60.0)}
    )
    runs = load_runs(tmp_path)
    detector = fit_from_runs(runs, APS, step_s=5, window_s=30, seed=42, n_estimators=50)
    direct = Detector.fit(normal_windows(runs, APS, 5, 30), feature_names(APS), 42, 50)
    probe = [w.features for r in runs for w in windows(r, APS, 5, 30)]
    assert detector.score(probe) == direct.score(probe)
    assert detector.names == feature_names(APS)


def test_no_normal_windows_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, {"flash-s43": ("flash", "val", 0.0)})
    with pytest.raises(ValueError, match="normal"):
        fit_from_runs(load_runs(tmp_path), APS, step_s=5, window_s=30, seed=42, n_estimators=10)
