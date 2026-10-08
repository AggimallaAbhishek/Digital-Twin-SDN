"""P4.4 live KPIs (controller/executor/live_kpis.py): measured network KPIs over a time window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from common.influx import InfluxConnection
from controller.executor.live_kpis import InfluxKpis, window_kpis

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "influx"
CONN = InfluxConnection("http://influx:8086", "org", "telemetry", "token")
START = datetime(2026, 10, 8, 9, 44, 20, tzinfo=UTC)


def _kpi(app: str, latency: float, thr: float = 1.0, loss: float = 0.0) -> dict[str, Any]:
    return {"app_class": app, "latency_ms": latency, "throughput_mbps": thr, "loss_pct": loss}


def _sta(name: str, ap: str | None, t: int = 0) -> dict[str, Any]:
    return {"sta": name, "ap": ap, "ts": START + timedelta(seconds=t)}


def test_window_kpis_use_the_problem_statement_definitions() -> None:
    kpis = [_kpi("video", 10, 1.0, 1.0), _kpi("video", 30, 0.5, 3.0), _kpi("bulk", 500, 2.0, 0.0)]
    stations = [_sta("sta1", "ap1"), _sta("sta2", "ap1"), _sta("sta3", "ap2")]
    aps = [{"ap": "ap1"}, {"ap": "ap2"}]
    result = window_kpis(kpis, stations, aps)
    assert result is not None
    assert result.throughput_mbps == pytest.approx(3.5 / 3)
    assert result.latency_ms == 30  # p95 of the video flows only (nearest rank of 2)
    assert result.loss_pct == pytest.approx(4 / 3)
    assert result.jain == pytest.approx(9 / (2 * 5))  # clients 2 and 1


def test_a_stations_latest_ap_in_the_window_counts() -> None:
    stations = [_sta("sta1", "ap1", t=0), _sta("sta1", "ap2", t=5), _sta("sta2", None)]
    result = window_kpis([_kpi("web", 5)], stations, [{"ap": "ap1"}, {"ap": "ap2"}])
    assert result is not None
    assert result.jain == pytest.approx(1 / 2)  # clients 0 and 1: 1 / (2 * 1)
    assert result.latency_ms == 5  # no video: p95 over every flow


def test_no_kpi_rows_means_no_kpis() -> None:
    assert window_kpis([], [_sta("sta1", "ap1")], [{"ap": "ap1"}]) is None


def test_no_ap_or_client_rows_gives_an_even_jain() -> None:
    result = window_kpis([_kpi("video", 5)], [], [])
    assert result is not None
    assert result.jain == 1.0


def test_influx_kpis_query_the_run_and_window() -> None:
    queries: list[str] = []
    files = {
        "kpi": "replay_kpi.csv",
        "sta_stats": "replay_sta_stats.csv",
        "ap_stats": "replay_ap_stats.csv",
    }

    def query(conn: InfluxConnection, flux: str, timeout_s: float) -> str:
        queries.append(flux)
        name = next(m for m in files if f'r._measurement == "{m}"' in flux)
        return (FIXTURES / files[name]).read_text()

    result = InfluxKpis(CONN, "smoke-cap", query=query).window(START, START + timedelta(seconds=10))
    assert result is not None
    # hand-computed from the 53 KPI rows of the replay: no video, so p95 over all flows
    assert result.throughput_mbps == pytest.approx(2.12417, abs=1e-5)
    assert result.loss_pct == pytest.approx(5.40883, abs=1e-5)
    assert result.latency_ms == pytest.approx(266.076)
    assert result.jain == pytest.approx(1.0)  # 5 clients on each of the 4 APs
    assert len(queries) == 3
    assert all('r.run_id == "smoke-cap"' in q for q in queries)
    assert all("2026-10-08T09:44:20+00:00" in q for q in queries)
