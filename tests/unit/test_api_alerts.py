"""Live anomaly alerts (api/alerts.py): the P4.2 detector over the last window of live telemetry."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from api.alerts import AlertMonitor, build_alert_monitor, influx_rows
from common.influx import InfluxConnection

T0 = datetime(2026, 10, 9, 10, 0, 30, tzinfo=UTC)
APS = ["ap1", "ap2"]


class FakeDetector:
    """Scores every window the same; names ap2 as the entity."""

    def __init__(self, score: float) -> None:
        self.value = score
        self.seen: list[list[float]] = []

    def score(self, windows: Sequence[Sequence[float]]) -> list[float]:
        self.seen += [list(w) for w in windows]
        return [self.value for _ in windows]

    def entity(self, window: Sequence[float]) -> str:
        return "ap2"


def _rows(start: datetime, end: datetime) -> tuple[list[Any], list[Any], list[Any]]:
    """30 s of telemetry: one row per AP, station and flow each second."""
    ap, sta, kpi = [], [], []
    t = start
    while t < end:
        ap += [{"ts": t, "ap": a, "channel_util": 0.5, "n_clients": 2} for a in APS]
        sta.append({"ts": t, "sta": "sta1", "ap": "ap1"})
        kpi.append({"ts": t, "loss_pct": 0.1, "latency_ms": 5.0})
        t += timedelta(seconds=1)
    return ap, sta, kpi


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _monitor(score: float, rows: Any = _rows) -> tuple[AlertMonitor, FakeDetector, Clock]:
    detector, clock = FakeDetector(score), Clock()
    return AlertMonitor(detector, APS, threshold=0.6, rows=rows, clock=clock), detector, clock


def test_a_window_scored_over_the_threshold_raises_an_alert() -> None:
    monitor, detector, _ = _monitor(0.7)
    alert = monitor.tick()
    assert alert == {
        "ts": T0.isoformat(),
        "detector": "isolation_forest",
        "entity": "ap2",
        "score": 0.7,
        "details": {"threshold": 0.6, "window_s": 30.0},
    }
    assert len(detector.seen) == 1  # the newest whole window only
    assert len(detector.seen[0]) == 2 * 5 + 3  # P4.2 features: 5 per AP + 3 network


def test_a_normal_window_raises_nothing() -> None:
    monitor, _, _ = _monitor(0.5)
    assert monitor.tick() is None
    assert monitor.recent(300) == []


def test_no_telemetry_raises_nothing() -> None:
    monitor, detector, _ = _monitor(0.9, rows=lambda start, end: ([], [], []))
    assert monitor.tick() is None
    assert detector.seen == []


def test_recent_returns_the_alerts_of_the_last_seconds() -> None:
    monitor, _, clock = _monitor(0.7)
    monitor.tick()
    clock.now += timedelta(seconds=120)
    monitor.tick()
    assert [a["ts"] for a in monitor.recent(60)] == [clock.now.isoformat()]
    assert len(monitor.recent(300)) == 2


def test_only_the_newest_alerts_are_kept() -> None:
    monitor, _, clock = _monitor(0.7)
    for _ in range(AlertMonitor.KEEP + 5):
        monitor.tick()
        clock.now += timedelta(seconds=5)
    assert len(monitor.recent(10**6)) == AlertMonitor.KEEP


def test_live_rows_are_one_runs_three_measurements_of_the_window() -> None:
    asked: list[str] = []

    def query(conn: InfluxConnection, flux: str, timeout_s: float) -> str:
        asked.append(flux)
        return ""

    conn = InfluxConnection("http://127.0.0.1:8086", "lab", "telemetry", "t")
    start = T0 - timedelta(seconds=30)
    assert influx_rows(conn, "live-1", query)(start, T0) == ([], [], [])
    assert [f.split('r._measurement == "')[1].split('"')[0] for f in asked] == [
        "ap_stats",
        "sta_stats",
        "kpi",
    ]
    assert all('r.run_id == "live-1"' in f and start.isoformat() in f for f in asked)


def test_no_dataset_turns_the_alerts_off(tmp_path: Path) -> None:
    assert build_alert_monitor(_rows, Clock(), dataset=tmp_path) is None
    assert build_alert_monitor(_rows, Clock(), threshold_file=tmp_path / "none.json") is None


class NoWaitStop(threading.Event):
    """A stop event whose wait between ticks returns at once."""

    def wait(self, timeout: float | None = None) -> bool:
        return self.is_set()


def test_a_failing_tick_is_logged_and_the_monitor_keeps_going() -> None:
    stop, calls = NoWaitStop(), []

    def rows(start: datetime, end: datetime) -> tuple[list[Any], list[Any], list[Any]]:
        calls.append(start)
        if len(calls) == 1:
            raise OSError("influx down")
        stop.set()
        return _rows(start, end)

    monitor = AlertMonitor(FakeDetector(0.7), APS, threshold=0.6, rows=rows, clock=Clock())
    monitor.run(stop)
    assert len(calls) == 2
    assert len(monitor.recent(60)) == 1


def test_less_than_one_window_of_telemetry_raises_nothing() -> None:
    monitor, detector, _ = _monitor(
        0.9, rows=lambda start, end: _rows(start, start + timedelta(seconds=10))
    )
    assert monitor.tick() is None
    assert detector.seen == []


def test_rows_with_empty_feature_cells_are_ignored() -> None:
    # found live (genai batch): an ap_stats row arrived with an empty channel_util cell (None)
    def gappy(start: datetime, end: datetime) -> tuple[list[Any], list[Any], list[Any]]:
        ap, sta, kpi = _rows(start, end)
        ap[0] = ap[0] | {"channel_util": None}
        kpi[0] = kpi[0] | {"latency_ms": None}
        return ap, sta, kpi

    monitor, detector, _ = _monitor(0.7, rows=gappy)
    complete, reference, _ = _monitor(0.7)
    assert monitor.tick() is not None
    complete.tick()
    # the same features as without those two rows (the other rows of their bins carry them)
    assert detector.seen == reference.seen
