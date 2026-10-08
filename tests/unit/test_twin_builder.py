"""P3.1 TwinState builder (twin/state/builder.py): edge cases on hand-made rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from twin.state.builder import CampusAPs, Snapshot, build_state, load_campus_aps

NOW = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
CAMPUS = CampusAPs(
    positions={"ap1": (20.0, 50.0), "ap2": (60.0, 50.0)}, channels={"ap1": 1, "ap2": 6}
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
    raw = {"aps": [{"name": "ap1", "position": [20, 50], "channel": 1}]}
    assert load_campus_aps(raw) == CampusAPs({"ap1": (20.0, 50.0)}, {"ap1": 1})


def test_flows_mapping_is_read_only() -> None:
    kpi = {
        "ts": NOW, "flow_id": "sta1-video", "app_class": "video",
        "throughput_mbps": 1.0, "latency_ms": 5.0, "jitter_ms": 1.0, "loss_pct": 0.0,
    }  # fmt: skip
    state = build_state(Snapshot([], [], [kpi]), CAMPUS, NOW, stale_s=5)
    with pytest.raises(TypeError):
        del state.flows["sta1-video"]  # type: ignore[attr-defined]  # proving it is read-only
