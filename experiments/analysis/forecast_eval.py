"""P4.1 forecaster evaluation: moving-average baseline vs Holt on the P2.3 dataset.

    uv run python -m experiments.analysis.forecast_eval          # config/forecast.yaml

Per AP and run, utilisation is resampled to 5 s. Rolling-origin evaluation: from every origin
with >= warmup of history, forecast t + 1 min and t + 3 min. Parameters (baseline window,
Holt alpha/beta) are chosen on the train split only (mean RMSE over both horizons); val
confirms them and test is reported once (RULEBOOK E-2, E-5). Forecasts are clipped to [0, 1].
Writes models/forecast/v1/params.json and metrics.json (E-4); this script is the only source
of the reported numbers (E-6).
"""

from __future__ import annotations

import itertools
import json
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from experiments.shell import git_commit
from ml.forecast.models import holt_forecast, moving_average_forecast
from ml.forecast.series import resample, rmse, rolling_errors

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "forecast" / "v1"
Series = list[float | None]
SeriesSet = dict[str, list[tuple[str, Series]]]  # split -> [(scenario, series)]


def load_series(dataset: Path, target: str, step_s: float) -> SeriesSet:
    """One resampled utilisation series per (run, AP), grouped by split."""
    table = pq.read_table(
        dataset / "ap_stats.parquet",
        columns=["run_id", "scenario_id", "split", "ap", "t_s", target],
    )
    points: dict[tuple[str, str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in table.to_pylist():
        key = (row["split"], row["scenario_id"], row["run_id"], row["ap"])
        points[key].append((row["t_s"], row[target]))
    out: SeriesSet = defaultdict(list)
    for (split, scenario, _run, _ap), pts in sorted(points.items()):
        out[split].append((scenario, resample(sorted(pts), step_s)))
    return out


def score(
    series: Sequence[tuple[str, Series]],
    forecaster: Callable[[Sequence[float], int], float],
    horizon_steps: int,
    warmup_steps: int,
) -> float:
    """RMSE over every rolling origin of every series (forecasts clipped to [0, 1])."""
    errors: list[float] = []
    for _scenario, s in series:
        errors += rolling_errors(
            s,
            lambda h: min(1.0, max(0.0, forecaster(h, horizon_steps))),
            horizon_steps,
            warmup_steps,
        )
    return rmse(errors)


def main() -> int:
    """Tune on train, report val and test; 0 always (an honest report is the deliverable)."""
    config: dict[str, Any] = yaml.safe_load((ROOT / "config" / "forecast.yaml").read_text())
    step = float(config["step_s"])
    horizons = [int(h / step) for h in config["horizons_s"]]
    warmup = int(config["warmup_s"] / step)
    data = load_series(ROOT / config["dataset"], config["target"], step)

    def mean_score(split: str, forecaster: Callable[[Sequence[float], int], float]) -> float:
        return statistics.mean(score(data[split], forecaster, h, warmup) for h in horizons)

    def baseline_score(w: int) -> float:
        return mean_score("train", lambda h, n: moving_average_forecast(h, w, n))

    def holt_score(ab: tuple[float, float]) -> float:
        return mean_score("train", lambda h, n: holt_forecast(h, ab[0], ab[1], n))

    window = min(config["baseline_windows"], key=baseline_score)
    alpha, beta = min(itertools.product(config["holt_alpha"], config["holt_beta"]), key=holt_score)
    models: dict[str, Callable[[Sequence[float], int], float]] = {
        "moving_average": lambda h, n: moving_average_forecast(h, window, n),
        "holt": lambda h, n: holt_forecast(h, alpha, beta, n),
    }
    metrics: dict[str, Any] = {}
    for split in ("train", "val", "test"):
        for name, f in models.items():
            for h_s, h in zip(config["horizons_s"], horizons, strict=True):
                metrics.setdefault(split, {}).setdefault(name, {})[f"rmse_{h_s}s"] = round(
                    score(data[split], f, h, warmup), 4
                )
    by_scenario: dict[str, Any] = {}
    for scenario in sorted({sc for sc, _ in data["test"]}):
        subset = [(sc, s) for sc, s in data["test"] if sc == scenario]
        for name, f in models.items():
            by_scenario.setdefault(scenario, {})[name] = {
                f"rmse_{h_s}s": round(score(subset, f, h, warmup), 4)
                for h_s, h in zip(config["horizons_s"], horizons, strict=True)
            }
    OUT.mkdir(parents=True, exist_ok=True)
    params = {"moving_average_window_steps": window, "holt_alpha": alpha, "holt_beta": beta}
    meta = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "dataset": config["dataset"],
        "config": config,
    }
    (OUT / "params.json").write_text(json.dumps({**params, **meta}, indent=1))
    (OUT / "metrics.json").write_text(
        json.dumps({"metrics": metrics, "test_by_scenario": by_scenario, **meta}, indent=1)
    )
    print(f"FORECAST_PARAMS {json.dumps(params)}")
    for split in ("val", "test"):
        for h_s in config["horizons_s"]:
            base = metrics[split]["moving_average"][f"rmse_{h_s}s"]
            holt = metrics[split]["holt"][f"rmse_{h_s}s"]
            verdict = "beats" if holt < base else "does not beat"
            print(f"FORECAST_{split.upper()} t+{h_s}s: holt {holt} vs baseline {base} -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
