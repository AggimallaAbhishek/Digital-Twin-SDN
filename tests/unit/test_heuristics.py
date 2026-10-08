"""P4.3 heuristic optimizer (ml/optimizer/heuristics.py) on fixture states of each scenario."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import SetApChannel, SteerClients
from ml.optimizer.heuristics import HeuristicConfig, load_heuristic_config, propose
from twin.radio import load_radio_params, predicted_rssi_dbm
from twin.state.model import APState, StationState, TwinState

ROOT = Path(__file__).resolve().parents[2]
RADIO = load_radio_params(yaml.safe_load((ROOT / "config/campus_v1.yaml").read_text()))
RAW_CONFIG: dict[str, Any] = yaml.safe_load((ROOT / "config/optimizer.yaml").read_text())
CONFIG = load_heuristic_config(RAW_CONFIG)
TS = datetime(2026, 10, 8, 10, 3, 30, tzinfo=UTC)
AP_POS = {"ap1": (20.0, 50.0), "ap2": (60.0, 50.0), "ap3": (20.0, 20.0), "ap4": (60.0, 20.0)}
DEFAULT_CHANNELS = {"ap1": 1, "ap2": 6, "ap3": 11, "ap4": 1}
NEAR_AP3 = {"sta1": (20.0, 36.0), "sta2": (23.0, 37.0), "sta3": (17.0, 38.0)}  # 14-18 m from ap3


def _state(
    util: dict[str, float],
    stations: Mapping[str, tuple[tuple[float, float], str | None]],
    channels: dict[str, int] | None = None,
    down: tuple[str, ...] = (),
) -> TwinState:
    channels = {**DEFAULT_CHANNELS, **(channels or {})}
    aps = {
        name: APState(name, pos, channels[name], name not in down, util.get(name, 0.1))
        for name, pos in AP_POS.items()
    }
    return TwinState(TS, aps, {n: StationState(n, pos, ap) for n, (pos, ap) in stations.items()})


def _hall_crowd(n_far: int) -> dict[str, tuple[tuple[float, float], str | None]]:
    """The 3 stations near ap3 plus `n_far` more at the far (north) side of the hall."""
    far = {f"sta{10 + i}": ((5.0 + 3 * i, 62.0), "ap1") for i in range(n_far)}
    return {**{n: (pos, "ap1") for n, pos in NEAR_AP3.items()}, **far}


def _steers(state: TwinState) -> list[SteerClients]:
    return [a for a in propose(state, CONFIG, RADIO) if isinstance(a, SteerClients)]


def _channels(state: TwinState) -> list[SetApChannel]:
    return [a for a in propose(state, CONFIG, RADIO) if isinstance(a, SetApChannel)]


# ------------------------------------------------------------------ config
def test_config_loads() -> None:
    assert HeuristicConfig(0.8, 0.6, 0.3, -75.0) == CONFIG


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"util_high": 1.5}, "util_high"),
        ({"util_target": 0.9}, "util_target"),  # must be below util_high
        ({"max_steer_fraction": 0}, "max_steer_fraction"),
        ({"min_target_rssi_dbm": "-75"}, "min_target_rssi_dbm"),
        ({"extra": 1}, "unknown"),
    ],
)
def test_bad_config_is_rejected(change: dict[str, Any], field: str) -> None:
    with pytest.raises(ValueError, match=field):
        load_heuristic_config({**RAW_CONFIG, **change})


# ------------------------------------------------------------------ normal
def test_a_calm_network_gets_no_proposals() -> None:
    state = _state({"ap1": 0.3, "ap2": 0.4, "ap3": 0.2, "ap4": 0.3}, _hall_crowd(4))
    assert propose(state, CONFIG, RADIO) == []


# ------------------------------------------------------------------ flash crowd: steering
def test_flash_crowd_steers_the_stations_near_the_idle_ap() -> None:
    state = _state({"ap1": 1.0, "ap2": 0.3, "ap3": 0.1, "ap4": 0.1}, _hall_crowd(10))  # 13 on ap1
    (steer,) = _steers(state)
    assert (steer.params.from_ap, steer.params.to_ap) == ("ap1", "ap3")
    assert set(steer.params.stations) == set(NEAR_AP3)  # 30% of 13 = 3, the 3 near ap3
    assert steer.source == "optimizer.heuristic"
    assert steer.created_at == TS
    assert "ap1" in steer.reason
    assert "ap3" in steer.reason


def test_steering_moves_at_most_30_percent_of_the_clients() -> None:
    state = _state({"ap1": 1.0}, _hall_crowd(4))  # 7 clients -> floor(2.1) = 2
    (steer,) = _steers(state)
    assert len(steer.params.stations) == 2


def test_an_ap_with_too_few_clients_to_move_30_percent_is_left_alone() -> None:
    assert _steers(_state({"ap1": 1.0}, _hall_crowd(0))) == []  # 3 clients -> 0.9 -> 0


def test_targets_must_have_room() -> None:
    busy = {"ap1": 1.0, "ap2": 0.7, "ap3": 0.65, "ap4": 0.9}
    assert _steers(_state(busy, _hall_crowd(10))) == []


def test_targets_must_give_a_usable_signal() -> None:
    far_only = {f"sta{10 + i}": ((5.0 + 3 * i, 62.0), "ap1") for i in range(10)}
    for name, (pos, _) in far_only.items():  # make sure the fixture really is out of range
        assert predicted_rssi_dbm(AP_POS["ap3"], pos, RADIO) < -75, name
    assert _steers(_state({"ap1": 1.0, "ap3": 0.1}, far_only)) == []


def test_steering_never_targets_a_down_ap() -> None:
    state = _state({"ap1": 1.0, "ap3": 0.1}, _hall_crowd(10), down=("ap3",))
    assert all(a.params.to_ap != "ap3" for a in _steers(state))


# ------------------------------------------------------------------ ap failure
def test_after_ap_failure_the_overloaded_neighbour_sheds_one_station() -> None:
    stations = {
        **{n: (pos, "ap1") for n, pos in NEAR_AP3.items()},
        "sta4": ((45.0, 50.2), "ap1"),
        "sta5": ((44.3, 48.4), "ap1"),
    }  # 5 clients on ap1 after ap2 failed -> floor(1.5) = 1
    (steer,) = _steers(_state({"ap1": 0.99, "ap3": 0.1, "ap4": 0.4}, stations, down=("ap2",)))
    assert steer.params.to_ap == "ap3"
    assert steer.params.stations == ["sta1"]  # the strongest predicted signal at ap3 (14 m)


# ------------------------------------------------------------------ co-channel interference
def test_default_channel_plan_is_already_the_best() -> None:
    assert _channels(_state({}, _hall_crowd(2))) == []


def test_ap3_forced_onto_channel_1_is_moved_back_to_11() -> None:
    (change,) = _channels(_state({"ap3": 0.95}, _hall_crowd(2), channels={"ap3": 1}))
    assert (change.params.ap, change.params.channel) == ("ap3", 11)
    assert change.type == "set_ap_channel"


def test_an_idle_ap_keeps_its_channel_even_when_it_shares_it() -> None:
    # a channel change is high-impact (needs approval): only worth it for a congested AP
    assert _channels(_state({"ap3": 0.2}, _hall_crowd(2), channels={"ap3": 1})) == []


def test_a_down_ap_does_not_count_as_interference() -> None:
    # ap1 and ap4 both on channel 1, but ap4 is down: nothing to fix
    assert _channels(_state({}, _hall_crowd(2), down=("ap4",))) == []


# ------------------------------------------------------------------ ids
def test_action_ids_are_unique_and_deterministic() -> None:
    state = _state(
        {"ap1": 1.0, "ap3": 0.1, "ap4": 0.9}, _hall_crowd(10), channels={"ap4": 6}
    )  # ap1 -> ap3 steer, and congested ap4 (sharing ch 6 with ap2, 30 m) changes channel
    first = [a.action_id for a in propose(state, CONFIG, RADIO)]
    again = [a.action_id for a in propose(state, CONFIG, RADIO)]
    assert first == again
    assert len(set(first)) == len(first) == 2
    assert first[0].startswith("act_20261008_100330_")


def test_different_proposals_in_the_same_second_get_different_ids() -> None:
    steer_only = _state({"ap1": 1.0, "ap3": 0.1}, _hall_crowd(10))
    channel_only = _state({"ap3": 0.95}, _hall_crowd(2), channels={"ap3": 1})
    (a,) = propose(steer_only, CONFIG, RADIO)
    (b,) = propose(channel_only, CONFIG, RADIO)
    assert a.action_id != b.action_id
