"""TwinState data model (twin/state/model.py)."""

from __future__ import annotations

from datetime import UTC, datetime

from twin.state.model import APState, StationState, TwinState

TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def _state() -> TwinState:
    return TwinState(
        ts=TS,
        aps={
            "ap1": APState("ap1", (20.0, 50.0), channel=1, up=True, util=0.9),
            "ap2": APState("ap2", (60.0, 50.0), channel=6, up=False, util=0.0),
        },
        stations={
            "sta10": StationState("sta10", (10.0, 40.0), ap="ap1"),
            "sta2": StationState("sta2", (25.0, 40.0), ap="ap1"),
            "sta3": StationState("sta3", (30.0, 30.0), ap=None),
        },
    )


def test_clients_are_derived_from_the_stations_in_station_order() -> None:
    assert _state().clients("ap1") == ("sta2", "sta10")
    assert _state().clients("ap2") == ()


def test_up_aps_excludes_failed_ones() -> None:
    assert [ap.name for ap in _state().up_aps()] == ["ap1"]
