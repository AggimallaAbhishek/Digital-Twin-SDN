"""P3.1 TwinState builder (twin/state/builder.py): edge cases on hand-made rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from twin.state.builder import CampusAPs, Snapshot, build_state, lag_s, load_campus_aps

NOW = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
CAMPUS = CampusAPs(
    positions={"ap1": (20.0, 50.0), "ap2": (60.0, 50.0)},
    channels={"ap1": 1, "ap2": 6},
    zones={"lab": ((40.0, 80.0), (35.0, 65.0))},
)


def _ap(name: str, age_s: float, channel: str = "1", util: float = 0.4) -> dict[str, Any]:
    return {
        "ts": NOW - timedelta(seconds=age_s),
        "ap": name,
        "channel": channel,
        "channel_util": util,
    }


def test_an_ap_that_never_reported_is_down_on_its_configured_channel() -> None:
    state = build_state(Snapshot([_ap("ap1", 1)], [], []), CAMPUS, NOW, stale_s=5)
    assert (state.aps["ap2"].up, state.aps["ap2"].channel, state.aps["ap2"].util) == (False, 6, 0.0)
    assert state.aps["ap1"].up


def test_a_station_without_an_ap_is_unassociated() -> None:
    sta = {"ts": NOW, "sta": "sta3", "ap": None, "x": 1.0, "y": 2.0}
    state = build_state(Snapshot([], [sta], []), CAMPUS, NOW, stale_s=5)
    assert state.stations["sta3"].ap is None


def test_no_telemetry_means_no_state() -> None:
    with pytest.raises(ValueError, match="no telemetry"):
        build_state(Snapshot([], [], []), CAMPUS, NOW, stale_s=5)


def test_campus_aps_come_from_the_config() -> None:
    raw = {
        "aps": [{"name": "ap1", "position": [20, 50], "channel": 1}],
        "zones": {"lab": {"x": [40, 80], "y": [35, 65]}},
    }
    assert load_campus_aps(raw) == CampusAPs(
        {"ap1": (20.0, 50.0)}, {"ap1": 1}, {"lab": ((40.0, 80.0), (35.0, 65.0))}
    )


def test_a_station_outside_every_zone_has_none() -> None:
    sta = {"ts": NOW, "sta": "sta3", "ap": "ap1", "x": 1.0, "y": 2.0}
    state = build_state(Snapshot([], [sta], []), CAMPUS, NOW, stale_s=5)
    assert state.stations["sta3"].zone is None


def test_flows_mapping_is_read_only() -> None:
    kpi = {
        "ts": NOW, "flow_id": "sta1-video", "app_class": "video",
        "throughput_mbps": 1.0, "latency_ms": 5.0, "jitter_ms": 1.0, "loss_pct": 0.0,
    }  # fmt: skip
    state = build_state(Snapshot([], [], [kpi]), CAMPUS, NOW, stale_s=5)
    with pytest.raises(TypeError):
        del state.flows["sta1-video"]  # type: ignore[attr-defined]  # proving it is read-only


def _sta(age_s: float) -> dict[str, Any]:
    return {"ts": NOW - timedelta(seconds=age_s), "sta": "sta1", "ap": "ap1", "x": 1.0, "y": 2.0}


def _kpi(age_s: float) -> dict[str, Any]:
    return {
        "ts": NOW - timedelta(seconds=age_s),
        "flow_id": "sta1-video",
        "app_class": "video",
        "throughput_mbps": 1.0,
        "latency_ms": 10.0,
        "loss_pct": 0.0,
    }


def test_lag_is_set_by_the_stalest_measurement_not_the_freshest_row() -> None:
    # AP and station telemetry stopped 8 s ago; a fresh KPI row must not hide that
    snapshot = Snapshot([_ap("ap1", 8)], [_sta(8)], [_kpi(0.5)])
    state = build_state(snapshot, CAMPUS, NOW, stale_s=5)
    assert lag_s(state, NOW) == pytest.approx(8.0)


def test_a_measurement_without_rows_does_not_set_the_lag() -> None:
    state = build_state(Snapshot([_ap("ap1", 1)], [_sta(2)], []), CAMPUS, NOW, stale_s=5)
    assert lag_s(state, NOW) == pytest.approx(2.0)


def test_an_empty_tx_power_cell_means_unknown_power() -> None:
    row = {**_ap("ap1", 1), "tx_power_dbm": None}  # parse_flux_csv turns "" into None
    state = build_state(Snapshot([row], [], []), CAMPUS, NOW, stale_s=5)
    assert state.aps["ap1"].tx_power_dbm is None


def test_an_incomplete_ap_row_is_ignored_in_favour_of_the_last_complete_one() -> None:
    # found live (V3 loop, seed 43): an ap_stats row came back with an empty channel_util cell
    complete = _ap("ap1", 2, util=0.4)
    broken = {**_ap("ap1", 1), "channel_util": None}
    state = build_state(Snapshot([complete, broken], [], []), CAMPUS, NOW, stale_s=5)
    assert state.aps["ap1"].util == 0.4
    assert state.aps["ap1"].up


def test_an_ap_with_only_incomplete_rows_counts_as_not_reporting() -> None:
    broken = {**_ap("ap1", 1), "channel": None}
    state = build_state(Snapshot([broken, _ap("ap2", 1)], [], []), CAMPUS, NOW, stale_s=5)
    assert not state.aps["ap1"].up
    assert state.aps["ap1"].channel == 1  # the configured channel
