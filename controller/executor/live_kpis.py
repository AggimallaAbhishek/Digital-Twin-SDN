"""P4.4 live KPIs: what the network measured over a time window, for the executor's watch.

Same definitions as the verifier (problem statement §5.1, decision P3.4-A), over every flow of
the run: mean throughput, p95 latency of the video flows (all flows if none is video), mean
loss, and Jain's index of the client count of the APs that reported in the window (a station
counts on the AP it was on last). Read from InfluxDB with common/influx.py.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from common.influx import InfluxConnection, parse_flux_csv, query_csv, rows_query
from common.schemas import (
    MEASUREMENTS,
    APStats,
    KPIRecord,
    KPIValues,
    StationStats,
    TelemetryRecord,
)

P95 = 0.95
QUERY_TIMEOUT_S = 10.0
Query = Callable[[InfluxConnection, str, float], str]
Row = dict[str, Any]  # a parsed Flux row: column -> value


def window_kpis(
    kpi_rows: Sequence[Row], sta_rows: Sequence[Row], ap_rows: Sequence[Row]
) -> KPIValues | None:
    """Network KPIs of one window's rows; None if no flow reported."""
    if not kpi_rows:
        return None
    video = sorted(r["latency_ms"] for r in kpi_rows if r["app_class"] == "video")
    latencies = video or sorted(r["latency_ms"] for r in kpi_rows)
    latest: dict[str, Row] = {}
    for row in sorted(sta_rows, key=lambda r: r["ts"]):
        latest[row["sta"]] = row
    aps = sorted({r["ap"] for r in ap_rows})
    clients = [sum(1 for r in latest.values() if r["ap"] == ap) for ap in aps]
    squares = sum(c * c for c in clients)
    return KPIValues(
        throughput_mbps=math.fsum(r["throughput_mbps"] for r in kpi_rows) / len(kpi_rows),
        latency_ms=latencies[math.ceil(P95 * len(latencies)) - 1],
        loss_pct=math.fsum(r["loss_pct"] for r in kpi_rows) / len(kpi_rows),
        jain=sum(clients) ** 2 / (len(clients) * squares) if squares else 1.0,
    )


class InfluxKpis:
    """Live KPIs of one run from InfluxDB (the executor's LiveKpis)."""

    def __init__(self, conn: InfluxConnection, run_id: str, query: Query = query_csv) -> None:
        self._conn, self._run_id, self._query = conn, run_id, query

    def window(self, start: datetime, end: datetime) -> KPIValues | None:
        """KPIs over [start, end); None if no flow reported in it."""
        return window_kpis(
            self._rows(KPIRecord, start, end),
            self._rows(StationStats, start, end),
            self._rows(APStats, start, end),
        )

    def _rows(self, model: type[TelemetryRecord], start: datetime, end: datetime) -> list[Row]:
        measurement = MEASUREMENTS[model]
        flux = rows_query(self._conn.bucket, measurement, start, end, run_id=self._run_id)
        return parse_flux_csv(self._query(self._conn, flux, QUERY_TIMEOUT_S), model)
