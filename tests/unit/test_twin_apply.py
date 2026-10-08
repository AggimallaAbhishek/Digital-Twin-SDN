"""P3.2 apply an allow-listed Action to a copy of the TwinState (twin/sim/apply.py).

One test per action type, each also checking the original state is untouched (RULEBOOK C-7).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from common.schemas import ACTION_ADAPTER, Action
from twin.sim.apply import apply
from twin.state.model import APState, FlowState, StationState, TwinState

TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def _state() -> TwinState:
    return TwinState(
        ts=TS,
        aps={
            "ap1": APState("ap1", (20.0, 50.0), channel=1, up=True, util=0.9, tx_power_dbm=14.0),
            "ap2": APState("ap2", (60.0, 50.0), channel=6, up=True, util=0.3, tx_power_dbm=14.0),
            "ap3": APState("ap3", (20.0, 20.0), channel=11, up=True, util=0.2, tx_power_dbm=14.0),
        },
        stations={
            "sta1": StationState("sta1", (14.0, 41.6), ap="ap1", zone="lecture_hall"),
            "sta2": StationState("sta2", (25.1, 39.7), ap="ap1", zone="lecture_hall"),
            "sta4": StationState("sta4", (45.0, 50.2), ap="ap2", zone="lab"),
            "sta5": StationState("sta5", (44.3, 48.4), ap="ap2", zone="lab"),
        },
        flows={
            "sta1-video": FlowState("sta1-video", "sta1", "video", 0.4, 20.0, 1.0),
            "sta4-video": FlowState("sta4-video", "sta4", "video", 1.0, 5.0, 0.0),
            "sta4-web": FlowState("sta4-web", "sta4", "web", 3.0, 8.0, 0.0),
        },
    )


def _action(kind: str, params: dict[str, Any]) -> Action:
    return ACTION_ADAPTER.validate_python(
        {
            "action_id": "act_test",
            "type": kind,
            "source": "operator",
            "reason": "test",
            "created_at": TS,
            "params": params,
        }
    )


def _applied(kind: str, params: dict[str, Any]) -> TwinState:
    """Apply to a fresh state and check the original was not changed."""
    state = _state()
    after = apply(state, _action(kind, params))
    assert state == _state()  # the original is never mutated (equal to a fresh build)
    assert after is not state
    return after


def test_steer_moves_the_stations() -> None:
    after = _applied("steer_clients", {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta2"]})
    assert (after.stations["sta2"].ap, after.stations["sta1"].ap) == ("ap3", "ap1")
    assert after.clients("ap3") == ("sta2",)


def test_set_channel_changes_only_that_ap() -> None:
    after = _applied("set_ap_channel", {"ap": "ap3", "channel": 1})
    assert {n: ap.channel for n, ap in after.aps.items()} == {"ap1": 1, "ap2": 6, "ap3": 1}


def test_set_tx_power() -> None:
    after = _applied("set_ap_tx_power", {"ap": "ap2", "dbm": 11})
    assert after.aps["ap2"].tx_power_dbm == 11.0


def test_ap_down_sends_its_stations_to_the_nearest_ap_that_is_up() -> None:
    after = _applied("ap_admin_state", {"ap": "ap2", "state": "down"})
    assert after.aps["ap2"].up is False
    assert after.aps["ap2"].util == 0.0
    # sta4 (45, 50.2) and sta5 (44.3, 48.4): ap1 at ~25 m, ap3 at ~39 m (P1.6-A rejoin rule)
    assert (after.stations["sta4"].ap, after.stations["sta5"].ap) == ("ap1", "ap1")


def test_ap_up_brings_nobody_back() -> None:
    down = apply(_state(), _action("ap_admin_state", {"ap": "ap2", "state": "down"}))
    up = apply(down, _action("ap_admin_state", {"ap": "ap2", "state": "up"}))
    assert up.aps["ap2"].up is True
    assert up.clients("ap2") == ()  # clients are sticky


def test_qos_queue_applies_to_matching_flows_only() -> None:
    after = _applied(
        "set_qos_queue", {"match": {"zone": "lab", "app_class": "video"}, "queue_id": 1}
    )
    assert {f: flow.queue_id for f, flow in after.flows.items()} == {
        "sta1-video": 0,  # video, but lecture hall
        "sta4-video": 1,
        "sta4-web": 0,  # lab, but web
    }


def test_qos_queue_by_flow_id() -> None:
    after = _applied("set_qos_queue", {"match": {"flow_id": "sta1-video"}, "queue_id": 2})
    assert after.flows["sta1-video"].queue_id == 2


def test_rate_limit_caps_the_flow() -> None:
    after = _applied("rate_limit_flow", {"flow_id": "sta4-web", "max_mbps": 1.5})
    assert after.flows["sta4-web"].rate_limit_mbps == 1.5
    assert after.flows["sta4-video"].rate_limit_mbps is None


def test_reroute_records_the_path() -> None:
    after = _applied(
        "reroute_flow", {"flow_id": "sta4-web", "path": ["srv1", "s1", "s2", "ap2", "sta4"]}
    )
    assert after.flows["sta4-web"].path == ("srv1", "s1", "s2", "ap2", "sta4")


@pytest.mark.parametrize(
    ("kind", "params", "message"),
    [
        ("set_ap_channel", {"ap": "ap9", "channel": 1}, "ap9"),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta9"]}, "sta9"),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta4"]}, "not on ap1"),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap9", "stations": ["sta1"]}, "ap9"),
        ("rate_limit_flow", {"flow_id": "sta9-web", "max_mbps": 2}, "sta9-web"),
        ("reroute_flow", {"flow_id": "nope", "path": ["srv1", "s1"]}, "nope"),
    ],
)
def test_actions_on_unknown_or_stale_targets_are_refused(
    kind: str, params: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        apply(_state(), _action(kind, params))


def test_down_with_no_ap_left_up_leaves_stations_unassociated() -> None:
    state = _state()
    for name in ("ap1", "ap3"):
        state = apply(state, _action("ap_admin_state", {"ap": name, "state": "down"}))
    after = apply(state, _action("ap_admin_state", {"ap": "ap2", "state": "down"}))
    assert {s.ap for s in after.stations.values()} == {None}
