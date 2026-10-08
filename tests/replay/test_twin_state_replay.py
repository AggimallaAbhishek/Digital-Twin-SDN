"""P3.1 replay test: recorded InfluxDB telemetry (smoke run, 10 s window) -> TwinState.

Expected values were read off the fixture CSVs independently of the builder (csv module).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from common.influx import parse_flux_csv
from common.schemas import APStats, KPIRecord, StationStats
from twin.state.builder import Snapshot, build_state, lag_s, load_campus_aps

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "influx"
CAMPUS = load_campus_aps(yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text()))
SNAPSHOT = Snapshot(
    ap_rows=parse_flux_csv((FIXTURES / "replay_ap_stats.csv").read_text(), APStats),
    sta_rows=parse_flux_csv((FIXTURES / "replay_sta_stats.csv").read_text(), StationStats),
    kpi_rows=parse_flux_csv((FIXTURES / "replay_kpi.csv").read_text(), KPIRecord),
)
NOW = datetime(2026, 10, 8, 9, 44, 30, tzinfo=UTC)
STALE_S = 5.0


def test_the_latest_record_of_each_series_wins() -> None:
    state = build_state(SNAPSHOT, CAMPUS, NOW, STALE_S)
    assert len(state.stations) == 20
    assert Counter(s.ap for s in state.stations.values()) == {
        "ap1": 5,
        "ap2": 5,
        "ap3": 5,
        "ap4": 5,
    }
    assert state.stations["sta10"].ap == "ap1"  # mid-walk earlier in the window, on ap1 at its end
    assert state.stations["sta10"].position == (21.2, 46.8)


def test_aps_carry_live_channel_and_utilisation_and_configured_position() -> None:
    state = build_state(SNAPSHOT, CAMPUS, NOW, STALE_S)
    assert {name: ap.channel for name, ap in state.aps.items()} == {
        "ap1": 1,
        "ap2": 6,
        "ap3": 1,
        "ap4": 1,
    }  # fmt: skip  (ap3 was just forced onto channel 1)
    assert all(ap.up for ap in state.aps.values())
    assert state.aps["ap4"].util == pytest.approx(0.5375, abs=1e-4)
    assert state.aps["ap1"].position == (20.0, 50.0)


def test_flows_carry_their_latest_kpis() -> None:
    state = build_state(SNAPSHOT, CAMPUS, NOW, STALE_S)
    assert len(state.flows) == 18
    bulk = state.flows["sta16-bulk"]
    assert (bulk.sta, bulk.app_class, bulk.throughput_mbps) == ("sta16", "bulk", 0.614)


def test_state_time_and_lag_come_from_the_newest_record() -> None:
    state = build_state(SNAPSHOT, CAMPUS, NOW, STALE_S)
    assert state.ts == datetime(2026, 10, 8, 9, 44, 29, 683000, tzinfo=UTC)
    assert lag_s(state, NOW) == pytest.approx(0.317)


def test_aps_without_recent_stats_are_down() -> None:
    later = datetime(2026, 10, 8, 9, 44, 40, tzinfo=UTC)  # 10.8 s after the last ap_stats
    state = build_state(SNAPSHOT, CAMPUS, later, STALE_S)
    assert not any(ap.up for ap in state.aps.values())


def test_aps_carry_tx_power_and_stations_their_zone() -> None:
    state = build_state(SNAPSHOT, CAMPUS, NOW, STALE_S)
    assert {ap.tx_power_dbm for ap in state.aps.values()} == {14.0}
    assert state.stations["sta10"].zone == "lecture_hall"  # (21.2, 46.8)
    assert state.stations["sta16"].zone == "library"
