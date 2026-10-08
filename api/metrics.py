"""P3.6 /metrics backend: one entity's telemetry series from InfluxDB.

An entity is an AP (ap_stats, tag ap), a station (sta_stats, tag sta) or a flow (kpi, tag
flow_id); the metric is one of that measurement's fields (common/schemas.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from common.influx import InfluxConnection, parse_flux_csv, query_csv, rows_query
from common.schemas import MEASUREMENTS, APStats, KPIRecord, StationStats, TelemetryRecord

QUERY_TIMEOUT_S = 10.0
_ENTITIES: list[tuple[re.Pattern[str], type[TelemetryRecord], str]] = [
    (re.compile(r"^ap[0-9]+$"), APStats, "ap"),
    (re.compile(r"^sta[0-9]+$"), StationStats, "sta"),
    (re.compile(r"^sta[0-9]+-[a-z]+$"), KPIRecord, "flow_id"),
]
Row = dict[str, Any]  # a parsed Flux row: column -> value


def measurement_for(entity: str) -> tuple[str, str]:
    """(measurement, tag) holding `entity`'s telemetry; ValueError for anything else."""
    for pattern, model, tag in _ENTITIES:
        if pattern.match(entity):
            return MEASUREMENTS[model], tag
    raise ValueError(f"unknown entity {entity!r}: expected apN, staN or staN-<app class>")


def series(
    rows: Sequence[Row], tag: str, entity: str, metric: str
) -> list[dict[str, Any]]:  # Any: JSON
    """[{ts, value}] of `metric` for `entity`, oldest first."""
    mine = sorted((r for r in rows if r.get(tag) == entity), key=lambda r: r["ts"])
    if mine and metric not in mine[0]:
        raise ValueError(f"unknown metric {metric!r} for {entity}")
    return [{"ts": r["ts"].isoformat(), "value": r[metric]} for r in mine]


def influx_metrics(
    conn: InfluxConnection, run_id: str, clock: Callable[[], datetime]
) -> Callable[[str, str, int], list[dict[str, Any]]]:  # Any: JSON
    """The API's metrics function over InfluxDB, for one run."""
    models = {MEASUREMENTS[m]: m for _, m, _ in _ENTITIES}

    def metrics(entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:  # Any: JSON
        measurement, tag = measurement_for(entity)
        end = clock()
        flux = rows_query(conn.bucket, measurement, end - timedelta(seconds=window_s), end, run_id)
        rows = parse_flux_csv(query_csv(conn, flux, QUERY_TIMEOUT_S), models[measurement])
        return series(rows, tag, entity, metric)

    return metrics
