"""P5.6 live anomaly alerts: the P4.2 detector over the newest window of live telemetry.

    monitor = build_alert_monitor(conn, run_id)    # None (with a log line) if data/v1 is missing
    monitor.tick()                                 # every step_s: score the last window_s
    monitor.recent(300)                            # alerts of the last 5 minutes (GET /alerts)

Each tick reads the last `window_s` (30 s) of ap_stats, sta_stats and kpi rows, turns them into
one P4.2 feature window (ml/anomaly/features.py, t_s relative to the window's start) and scores
it. A score over the threshold chosen on the val split (models/anomaly/v1/metrics.json) is an
alert, kept in memory (the newest KEEP). The detector is refitted at start-up from the dataset
in config/anomaly.yaml with the same code as the offline evaluation (ml/anomaly/training.py),
so no pickled model is ever loaded.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from api.wiring import ROOT, load_yaml
from common.influx import InfluxConnection, parse_flux_csv, query_csv, rows_query
from common.schemas import MEASUREMENTS, APStats, KPIRecord, StationStats, TelemetryRecord
from ml.anomaly.features import RunRows, windows
from ml.anomaly.training import fit_from_runs, load_runs
from twin.state.builder import load_campus_aps

log = logging.getLogger("api.alerts")
Rows = list[dict[str, Any]]  # Any: telemetry columns
RowSource = Callable[[datetime, datetime], tuple[Rows, Rows, Rows]]  # ap, sta, kpi in [start, end)
THRESHOLD_FILE = ROOT / "models" / "anomaly" / "v1" / "metrics.json"
QUERY_TIMEOUT_S = 5.0


class Scorer(Protocol):
    """What the monitor needs of ml.anomaly.detector.Detector."""

    def score(self, windows: Sequence[Sequence[float]]) -> list[float]: ...

    def entity(self, window: Sequence[float]) -> str: ...


class AlertMonitor:
    """Scores the newest telemetry window each tick; remembers the windows over the threshold."""

    KEEP = 720  # one hour of alerts at one per 5 s tick

    def __init__(  # noqa: PLR0913 - window settings travel as given in config/anomaly.yaml
        self,
        detector: Scorer,
        aps: Sequence[str],
        *,
        threshold: float,
        rows: RowSource,
        clock: Callable[[], datetime],
        step_s: float = 5.0,
        window_s: float = 30.0,
    ) -> None:
        self._detector, self._aps, self._threshold = detector, list(aps), threshold
        self._rows, self._clock, self._step, self._window = rows, clock, step_s, window_s
        self._alerts: deque[dict[str, Any]] = deque(maxlen=self.KEEP)
        self._lock = threading.Lock()  # tick() runs in a thread, recent() in request handlers

    def tick(self) -> dict[str, Any] | None:  # Any: JSON
        """Score the last window_s of telemetry; the alert if it is over the threshold."""
        now = self._clock()
        start = now - timedelta(seconds=self._window)
        ap, sta, kpi = self._rows(start, now)
        if not ap and not sta and not kpi:
            return None  # no telemetry at all (testbed down): nothing to judge

        def relative(rows: Rows) -> Rows:
            return [r | {"t_s": (r["ts"] - start).total_seconds()} for r in rows]

        run = RunRows("live", "live", "live", None, relative(ap), relative(sta), relative(kpi))
        found = windows(run, self._aps, self._step, self._window)
        if not found:
            return None  # less than one window of data yet
        features = found[-1].features
        [score] = self._detector.score([features])
        if score <= self._threshold:
            return None
        alert = {
            "ts": now.isoformat(),
            "detector": "isolation_forest",
            "entity": self._detector.entity(features),
            "score": score,
            "details": {"threshold": self._threshold, "window_s": self._window},
        }
        with self._lock:
            self._alerts.append(alert)
        return alert

    def recent(self, seconds: float) -> list[dict[str, Any]]:  # Any: JSON
        """The alerts raised in the last `seconds`, oldest first."""
        since = self._clock() - timedelta(seconds=seconds)
        with self._lock:
            return [a for a in self._alerts if datetime.fromisoformat(a["ts"]) >= since]

    def run(self, stop: threading.Event) -> None:
        """tick() every step_s until `stop` is set; a failing tick is logged, not fatal."""
        while not stop.is_set():
            try:
                alert = self.tick()
                if alert is not None:
                    log.info("alert %s score %.3f", alert["entity"], alert["score"])
            except Exception:  # keep watching: one failed query must not stop the monitor
                log.exception("alert tick failed")
            stop.wait(self._step)


def influx_rows(
    conn: InfluxConnection,
    run_id: str,
    query: Callable[[InfluxConnection, str, float], str] = query_csv,
) -> RowSource:
    """ap_stats, sta_stats and kpi rows of `run_id` in [start, end) from InfluxDB."""

    def rows(start: datetime, end: datetime) -> tuple[Rows, Rows, Rows]:
        def read(model: type[TelemetryRecord]) -> Rows:
            flux = rows_query(conn.bucket, MEASUREMENTS[model], start, end, run_id=run_id)
            return parse_flux_csv(query(conn, flux, QUERY_TIMEOUT_S), model)

        return read(APStats), read(StationStats), read(KPIRecord)

    return rows


def build_alert_monitor(
    rows: RowSource, clock: Callable[[], datetime], root: Path = ROOT
) -> AlertMonitor | None:
    """The live monitor, its detector refitted from config/anomaly.yaml's dataset (about 2 s);
    None, logged, when that dataset or the chosen threshold is missing."""
    config = load_yaml("anomaly.yaml")
    dataset = root / config["dataset"]
    threshold_file = root / THRESHOLD_FILE.relative_to(ROOT)
    if not (dataset / "ap_stats.parquet").exists() or not threshold_file.exists():
        log.warning("alerts off: %s or %s is missing", dataset, threshold_file)
        return None
    aps = sorted(load_campus_aps(load_yaml("campus_v1.yaml")).positions)
    step_s, window_s = float(config["step_s"]), float(config["window_s"])
    detector = fit_from_runs(
        load_runs(dataset),
        aps,
        step_s=step_s,
        window_s=window_s,
        seed=int(config["seed"]),
        n_estimators=int(config["n_estimators"]),
    )
    threshold = float(json.loads(threshold_file.read_text())["threshold"])
    return AlertMonitor(
        detector,
        aps,
        threshold=threshold,
        rows=rows,
        clock=clock,
        step_s=step_s,
        window_s=window_s,
    )
