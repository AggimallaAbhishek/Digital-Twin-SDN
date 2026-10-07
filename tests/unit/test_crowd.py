"""P1.4 scheduled-crowd mobility planning (testbed/mobility/crowd.py)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from testbed.layout import load_layout, place_stations
from testbed.mobility.crowd import (
    WALK_SPEED_MPS,
    CrowdGroupSpec,
    Walk,
    nearest_ap,
    parse_groups,
    plan_crowd,
    position_at,
)

LAYOUT = load_layout(Path(__file__).resolve().parents[2] / "config" / "campus_v1.yaml")
STATIONS = place_stations(LAYOUT)  # sta9-sta15 start in the corridor, sta16-sta20 in the library
CORRIDOR = {s.name for s in STATIONS if s.zone == "corridor"}

GROUP = {"stations": 6, "from": "corridor", "to": "lecture_hall", "start_s": 120, "spread_s": 60}


def test_groups_parse_with_schema_field_names() -> None:
    assert parse_groups([GROUP]) == [CrowdGroupSpec(6, "corridor", "lecture_hall", 120.0, 60.0)]


def test_spread_defaults_to_zero() -> None:
    raw = {k: v for k, v in GROUP.items() if k != "spread_s"}
    assert parse_groups([raw])[0].spread_s == 0.0


@pytest.mark.parametrize(
    "change",
    [
        {"stations": 0},
        {"stations": 2.5},
        {"stations": True},
        {"to": "corridor"},
        {"start_s": -1},
        {"spread_s": -5},
        {"start_s": "soon"},
        {"from": 3},
        {"speed": 2},
    ],
    ids=[
        "no-stations",
        "fractional",
        "bool",
        "same-zone",
        "negative-start",
        "negative-spread",
        "string-time",
        "zone-not-str",
        "unknown-key",
    ],
)
def test_bad_groups_are_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="crowd group 0"):
        parse_groups([{**GROUP, **change}])


def test_missing_key_is_rejected() -> None:
    raw = {k: v for k, v in GROUP.items() if k != "to"}
    with pytest.raises(ValueError, match="'to'"):
        parse_groups([raw])


def _plan(*groups: CrowdGroupSpec, seed: int = 1) -> list[Walk]:
    return plan_crowd(list(groups), LAYOUT, STATIONS, seed=seed)


FLASH = (
    CrowdGroupSpec(6, "corridor", "lecture_hall", 120.0, 60.0),
    CrowdGroupSpec(4, "library", "lecture_hall", 120.0, 60.0),
)


def test_plan_picks_distinct_stations_from_each_source_zone() -> None:
    walks = _plan(*FLASH)

    names = [w.sta for w in walks]
    assert len(names) == len(set(names)) == 10
    zones = {s.name: s.zone for s in STATIONS}
    assert sorted(zones[n] for n in names) == ["corridor"] * 6 + ["library"] * 4


def test_plan_is_deterministic_per_seed() -> None:
    assert _plan(*FLASH, seed=1) == _plan(*FLASH, seed=1)
    assert [w.sta for w in _plan(*FLASH, seed=1)] != [w.sta for w in _plan(*FLASH, seed=2)]


def test_walks_start_at_the_station_and_end_inside_the_target_zone() -> None:
    start = {s.name: s.position for s in STATIONS}
    hall = LAYOUT.zones["lecture_hall"]
    m = LAYOUT.margin_m
    for walk in _plan(*FLASH):
        assert walk.src == start[walk.sta]
        x, y = walk.dst
        assert hall.x_min + m <= x <= hall.x_max - m
        assert hall.y_min + m <= y <= hall.y_max - m


def test_departures_are_spread_evenly_over_the_window() -> None:
    walks = _plan(CrowdGroupSpec(3, "corridor", "lab", 100.0, 20.0))
    assert [w.start_s for w in walks] == [100.0, 110.0, 120.0]


def test_a_single_walker_leaves_at_the_start_time() -> None:
    assert [w.start_s for w in _plan(CrowdGroupSpec(1, "corridor", "lab", 7.0, 20.0))] == [7.0]


def test_walk_duration_follows_distance_at_walking_speed() -> None:
    walk = _plan(CrowdGroupSpec(1, "corridor", "lab", 0.0))[0]
    distance = math.dist(walk.src, walk.dst)
    assert walk.duration_s == pytest.approx(distance / WALK_SPEED_MPS)
    assert walk.end_s == pytest.approx(walk.start_s + walk.duration_s)


def test_too_few_stations_in_the_source_zone_is_an_error() -> None:
    with pytest.raises(ValueError, match="corridor has 7"):
        _plan(CrowdGroupSpec(8, "corridor", "lab", 0.0))


def test_unknown_zone_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown zone 'roof'"):
        _plan(CrowdGroupSpec(1, "corridor", "roof", 0.0))


def test_later_groups_see_where_earlier_groups_went() -> None:
    walks = _plan(
        CrowdGroupSpec(7, "corridor", "lab", 0.0),  # empties the corridor ...
        CrowdGroupSpec(12, "lab", "library", 300.0),  # ... so the lab now holds 5 + 7
    )

    first = {w.sta: w for w in walks[:7]}
    second = walks[7:]
    assert set(first) == CORRIDOR
    for walk in second:
        if walk.sta in first:  # a corridor walker leaves from where it arrived
            assert walk.src == first[walk.sta].dst


def test_stations_still_walking_cannot_join_a_later_group() -> None:
    # all 7 corridor stations are still walking to the lab when the lab group leaves at t=1 s,
    # so only the 5 original lab stations are free
    with pytest.raises(ValueError, match="lab has 5 free stations at t=1 s, needs 6"):
        _plan(CrowdGroupSpec(7, "corridor", "lab", 0.0), CrowdGroupSpec(6, "lab", "library", 1.0))


WALK = Walk("sta9", start_s=10.0, src=(0.0, 0.0), dst=(12.0, 0.0), speed_mps=1.2)  # 10 s walk


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (0.0, (0.0, 0.0)),
        (10.0, (0.0, 0.0)),
        (15.0, (6.0, 0.0)),
        (20.0, (12.0, 0.0)),
        (99.0, (12.0, 0.0)),
    ],
    ids=["before", "leaving", "halfway", "arriving", "after"],
)
def test_position_moves_along_the_straight_path(t: float, expected: tuple[float, float]) -> None:
    assert position_at(WALK, t) == pytest.approx(expected)


def test_a_zero_length_walk_stays_put() -> None:
    walk = Walk("sta9", 0.0, (5.0, 5.0), (5.0, 5.0))
    assert walk.duration_s == 0.0
    assert position_at(walk, 1.0) == (5.0, 5.0)


@pytest.mark.parametrize(
    ("position", "ap"),
    [((20.0, 50.0), "ap1"), ((35.0, 40.0), "ap1"), ((61.0, 49.0), "ap2"), ((5.0, 5.0), "ap3")],
)
def test_nearest_ap(position: tuple[float, float], ap: str) -> None:
    assert nearest_ap(LAYOUT, position) == ap


def test_every_arrival_in_the_lecture_hall_is_nearest_to_ap1() -> None:
    # decision P1.4-A: walkers join the nearest AP on arrival, so a flash crowd lands on ap1
    for walk in _plan(*FLASH):
        assert nearest_ap(LAYOUT, walk.dst) == "ap1"
