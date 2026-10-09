"""P3.5 validation batch (experiments/validation_actions.py): schedule -> actions, and their t_s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from experiments.validation_actions import (
    ActionStep,
    actions_for,
    load_schedule,
    timed_actions,
)
from ml.optimizer.heuristics import HeuristicConfig
from twin.radio import RadioParams
from twin.state.model import APState, FlowState, StationState, TwinState

TS = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
RADIO = RadioParams(4.6, 30.0, 60.0, -16.0, 4.0)
HEURISTICS = HeuristicConfig(
    util_high=0.8, util_target=0.5, max_steer_fraction=0.3, min_target_rssi_dbm=-75.0
)
STATE = TwinState(
    TS,
    {
        "ap1": APState("ap1", (0.0, 0.0), 1, True, 0.9, 14.0),
        "ap2": APState("ap2", (20.0, 0.0), 6, True, 0.1, 14.0),
    },
    {
        "sta1": StationState("sta1", (2.0, 0.0), "ap1", "lab"),
        "sta2": StationState("sta2", (15.0, 0.0), "ap1", "lab"),  # nearest to ap2
        "sta3": StationState("sta3", (1.0, 0.0), "ap1", "lab"),
        "sta4": StationState("sta4", (1.0, 1.0), "ap1", "lab"),
    },
    {"sta1-video": FlowState("sta1-video", "sta1", "video", 1.0, 2.0, 0.0)},
)


def _schedule(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"normal": steps}


def test_the_schedule_is_read_per_scenario_in_time_order() -> None:
    raw = _schedule(
        [
            {
                "at_s": 240,
                "type": "set_qos_queue",
                "params": {"match": {"zone": "lab"}, "queue_id": 1},
            },
            {"at_s": 120, "type": "steer_one", "params": {"from_ap": "ap1", "to_ap": "ap2"}},
        ]
    )
    [first, second] = load_schedule(raw)["normal"]
    assert (first.at_s, first.type) == (120, "steer_one")
    assert (second.at_s, second.type) == (240, "set_qos_queue")


@pytest.mark.parametrize(
    "step",
    [
        {"at_s": -1, "type": "set_qos_queue", "params": {}},
        {"at_s": 10, "type": "drop_table", "params": {}},
        {"at_s": 10, "type": "heuristic", "params": {"x": 1}},
        {"type": "heuristic"},
    ],
)
def test_bad_steps_are_refused(step: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="step"):
        load_schedule(_schedule([step]))


def test_steer_one_moves_the_client_with_the_strongest_signal_at_the_target() -> None:
    step = ActionStep(120, "steer_one", {"from_ap": "ap1", "to_ap": "ap2"})
    [action] = actions_for(step, STATE, RADIO, HEURISTICS, "normal-s45")
    assert action.type == "steer_clients"
    assert action.params.model_dump() == {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta2"]}
    assert action.action_id.startswith("act_")
    assert action.source == "operator"


def test_an_explicit_step_becomes_that_action() -> None:
    step = ActionStep(330, "rate_limit_flow", {"flow_id": "sta1-video", "max_mbps": 1.0})
    [action] = actions_for(step, STATE, RADIO, HEURISTICS, "normal-s45")
    assert (action.type, action.params.model_dump()) == (
        "rate_limit_flow",
        {"flow_id": "sta1-video", "max_mbps": 1.0},
    )


def test_a_heuristic_step_asks_the_optimizer() -> None:
    step = ActionStep(270, "heuristic", {})
    actions = actions_for(step, STATE, RADIO, HEURISTICS, "flash-s45")
    assert [a.type for a in actions] == ["steer_clients"]  # ap1 at 90%, ap2 at 10%
    assert actions[0].source == "optimizer.heuristic"


def test_steer_one_with_no_client_gives_no_action() -> None:
    step = ActionStep(120, "steer_one", {"from_ap": "ap2", "to_ap": "ap1"})
    assert actions_for(step, STATE, RADIO, HEURISTICS, "normal-s45") == []


def test_applied_actions_get_their_scenario_time() -> None:
    t0 = TS
    lines = [
        {
            "run_id": "normal-s45",
            "utc": (t0 + timedelta(seconds=120.5)).isoformat(),
            "applied": True,
            "action": {"x": 1},
        },
        {
            "run_id": "normal-s45",
            "utc": (t0 + timedelta(seconds=240)).isoformat(),
            "applied": False,
            "action": {"x": 2},
        },
    ]
    assert timed_actions(lines, t0) == [{"run_id": "normal-s45", "t_s": 120.5, "action": {"x": 1}}]
