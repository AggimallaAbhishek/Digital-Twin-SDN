"""P4.2 detector training from a P2.3 dataset, shared by the offline evaluation and the live alert
monitor (api/alerts.py), so the live detector is fitted the same way as the evaluated one.

A run's disruption onset is read from the dataset's own `phase` label (decision P2.3-C: rows are
"stress" from the onset on), so training needs no scenario files. The detector is fitted on the
train split's normal windows only: normal runs, and windows of disrupted runs that end before
any stress (ml/anomaly/features.py).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ml.anomaly.detector import Detector
from ml.anomaly.features import RunRows, feature_names, windows

COLUMNS = {
    "ap_stats": [
        "run_id",
        "scenario_id",
        "split",
        "t_s",
        "phase",
        "ap",
        "channel_util",
        "n_clients",
    ],
    "sta_stats": ["run_id", "t_s", "sta", "ap"],
    "kpi": ["run_id", "t_s", "phase", "loss_pct", "latency_ms"],
}
TRAIN = "train"


def onset_of(ap_rows: Sequence[dict[str, Any]]) -> float | None:
    """A run's disruption onset: its first stress-labelled second, or None (decision P2.3-C)."""
    stress = [r["t_s"] for r in ap_rows if r["phase"] == "stress"]
    return min(stress) if stress else None


def load_runs(dataset: Path) -> list[RunRows]:
    """Every run of a dataset directory, with its onset (first stress-labelled second, or None)."""
    by_run: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for name, columns in COLUMNS.items():
        for row in pq.read_table(dataset / f"{name}.parquet", columns=columns).to_pylist():
            by_run[row["run_id"]][name].append(row)
    runs = []
    for run_id, rows in sorted(by_run.items()):
        first = rows["ap_stats"][0]
        runs.append(
            RunRows(
                run_id,
                first["scenario_id"],
                first["split"],
                onset_of(rows["ap_stats"]),
                rows["ap_stats"],
                rows["sta_stats"],
                rows["kpi"],
            )
        )
    return runs


def normal_windows(
    runs: Sequence[RunRows], aps: Sequence[str], step_s: float, window_s: float
) -> list[list[float]]:
    """Feature vectors of the train split's windows that hold no stress."""
    return [
        w.features
        for run in runs
        if run.split == TRAIN
        for w in windows(run, aps, step_s, window_s)
        if not w.stress
    ]


def fit_from_runs(  # noqa: PLR0913 - the detector's settings travel as given in config/anomaly.yaml
    runs: Sequence[RunRows],
    aps: Sequence[str],
    *,
    step_s: float,
    window_s: float,
    seed: int,
    n_estimators: int,
) -> Detector:
    """An Isolation Forest fitted on the train split's normal windows (seeded: RULEBOOK E-1)."""
    normal = normal_windows(runs, aps, step_s, window_s)
    if not normal:
        raise ValueError("no normal train-split windows to fit the detector on")
    return Detector.fit(normal, feature_names(aps), seed, n_estimators)
