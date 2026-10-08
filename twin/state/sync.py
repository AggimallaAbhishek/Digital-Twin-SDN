"""P3.1 incremental state sync: the last few seconds of a run in InfluxDB -> TwinState.

    sync = TwinSync(InfluxConnection.from_env(), campus, run_id, load_sync_config(raw))
    state = sync.refresh()
    lag_s(state, datetime.now(UTC)) # measured when the state is used, so it includes the queries

Each refresh reads only the last `sync_window_s` of the run (ap_stats, sta_stats, kpi), not the
whole history, and rebuilds the state from the latest record of each series (builder.py).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any

from common.influx import InfluxConnection, parse_flux_csv, query_csv, rows_query
from common.schemas import MEASUREMENTS, APStats, KPIRecord, StationStats, TelemetryRecord
from twin.state.builder import CampusAPs, Snapshot, build_state
from twin.state.model import TwinState

Query = Callable[[InfluxConnection, str, float], str]


@dataclass(frozen=True)
class SyncConfig:
    """config/twin.yaml (sync part)."""

    sync_window_s: float
    ap_stale_s: float
    max_lag_s: float
    query_timeout_s: float


def load_sync_config(raw: Mapping[str, Any]) -> SyncConfig:
    """Validate config/twin.yaml; ValueError names the bad field."""
    names = [f.name for f in fields(SyncConfig)]
    unknown = set(raw) - set(names)
    if unknown:
        raise ValueError(f"twin config: unknown keys {sorted(unknown)}")
    for name in names:
        value = raw.get(name)
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a number > 0, got {value!r}")
    return SyncConfig(*(float(raw[n]) for n in names))


class TwinSync:
    """Rebuilds the TwinState of one run from its recent telemetry."""

    def __init__(
        self,
        conn: InfluxConnection,
        campus: CampusAPs,
        run_id: str,
        config: SyncConfig,
        query: Query = query_csv,
    ) -> None:
        self._conn, self._campus, self._run_id, self._config = conn, campus, run_id, config
        self._query = query

    def refresh(self, now: datetime | None = None) -> TwinState:
        """The state as of `now` (default: the current time); ValueError if no telemetry yet.

        Its lag is `builder.lag_s(state, t)` at the time t the state is used, which includes the
        time these queries took."""
        at = now or datetime.now(UTC)
        start = at - timedelta(seconds=self._config.sync_window_s)
        snapshot = Snapshot(
            ap_rows=self._rows(APStats, start, at),
            sta_rows=self._rows(StationStats, start, at),
            kpi_rows=self._rows(KPIRecord, start, at),
        )
        return build_state(snapshot, self._campus, at, self._config.ap_stale_s)

    def _rows(
        self, model: type[TelemetryRecord], start: datetime, stop: datetime
    ) -> list[dict[str, Any]]:
        measurement = MEASUREMENTS[model]
        flux = rows_query(self._conn.bucket, measurement, start, stop, run_id=self._run_id)
        return parse_flux_csv(self._query(self._conn, flux, self._config.query_timeout_s), model)
