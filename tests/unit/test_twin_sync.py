"""P3.1 incremental sync (twin/state/sync.py) with a fake InfluxDB serving recorded CSV."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.influx import InfluxConnection
from twin.state.builder import lag_s, load_campus_aps
from twin.state.sync import SyncConfig, TwinSync, load_sync_config

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "influx"
CAMPUS = load_campus_aps(yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text()))
CONFIG = load_sync_config(yaml.safe_load((ROOT / "config" / "twin.yaml").read_text()))
CONN = InfluxConnection("http://127.0.0.1:8086", "lab", "telemetry", "t")
NOW = datetime(2026, 10, 8, 9, 44, 30, tzinfo=UTC)


class FakeInflux:
    """Answers each Flux query with the recorded CSV of the measurement it asks for."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, conn: InfluxConnection, flux: str, timeout_s: float) -> str:
        self.queries.append(flux)
        for name in ("ap_stats", "sta_stats", "kpi"):
            if f'r._measurement == "{name}"' in flux:
                return (FIXTURES / f"replay_{name}.csv").read_text()
        return ""


def test_config_loads() -> None:
    assert SyncConfig(10.0, 5.0, 3.0, 10.0) == CONFIG


@pytest.mark.parametrize("change", [{"sync_window_s": 0}, {"max_lag_s": "3"}, {"extra": 1}])
def test_bad_config_is_rejected(change: dict[str, Any]) -> None:
    raw = {**yaml.safe_load((ROOT / "config" / "twin.yaml").read_text()), **change}
    with pytest.raises(ValueError, match=next(iter(change))):
        load_sync_config(raw)


def test_refresh_reads_the_recent_window_of_one_run() -> None:
    influx = FakeInflux()
    sync = TwinSync(CONN, CAMPUS, "smoke-cap", CONFIG, query=influx)
    state = sync.refresh(NOW)
    assert len(state.stations) == 20
    assert len(influx.queries) == 3
    assert all('r.run_id == "smoke-cap"' in q for q in influx.queries)
    assert all(
        "range(start: 2026-10-08T09:44:20+00:00, stop: 2026-10-08T09:44:30+00:00)" in q
        for q in influx.queries
    )
    assert lag_s(state, NOW) == pytest.approx(0.827)  # stalest measurement: sta_stats 29.173


def test_no_telemetry_yet_is_an_error() -> None:
    sync = TwinSync(CONN, CAMPUS, "smoke-cap", CONFIG, query=lambda conn, flux, timeout_s: "")
    with pytest.raises(ValueError, match="no telemetry"):
        sync.refresh(NOW)
