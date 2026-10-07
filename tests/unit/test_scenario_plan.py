"""P1.6 scenario planning (testbed/scenario_plan.py): parse, selectors, timeline, summaries."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from testbed.layout import load_layout, place_stations
from testbed.mobility.crowd import Walk
from testbed.scenario_plan import (
    EventSpec,
    Step,
    TrafficSpec,
    max_deviation_pct,
    nearest_up_ap,
    parse_scenario,
    resolve_selector,
    summarize_kpis,
    timeline,
    zones_at,
)

LAYOUT = load_layout(Path(__file__).resolve().parents[2] / "config" / "campus_v1.yaml")
STATIONS = place_stations(LAYOUT)  # sta1-3 lecture_hall, 4-8 lab, 9-15 corridor, 16-20 library
RAW: dict[str, Any] = {
    "scenario_id": "lecture_flash_crowd",
    "duration_s": 600,
    "seed": 42,
    "topology": "campus_v1",
    "mobility": {
        "model": "scheduled_crowd",
        "groups": [{"stations": 6, "from": "corridor", "to": "lecture_hall", "start_s": 120}],
    },
    "traffic": [
        {"profile": "web", "stations": "*", "start_s": 0},
        {"profile": "video", "stations": "lecture_hall:*", "start_s": 210, "rate_mbps": 0.5},
    ],
    "events": [{"at_s": 300, "type": "force_channel", "ap": "ap3", "channel": 1}],
    "labels": ["congestion"],
}


def _with(**changes: Any) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    raw.update(changes)
    return raw


# ------------------------------------------------------------------ parse
def test_scenario_parses() -> None:
    spec = parse_scenario(RAW)
    assert (spec.scenario_id, spec.duration_s, spec.seed, spec.topology) == (
        "lecture_flash_crowd",
        600.0,
        42,
        "campus_v1",
    )
    assert len(spec.groups) == 1
    assert spec.traffic == (
        TrafficSpec("web", "*", 0.0, None),
        TrafficSpec("video", "lecture_hall:*", 210.0, 0.5),
    )
    assert spec.events == (EventSpec(300.0, "force_channel", "ap3", 1),)
    assert spec.labels == ("congestion",)


def test_static_scenario_needs_no_mobility_or_events() -> None:
    raw = {k: v for k, v in RAW.items() if k not in ("mobility", "events", "labels")}
    spec = parse_scenario(raw)
    assert (spec.groups, spec.events, spec.labels) == ((), (), ())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"duration_s": 0}, "duration_s"),
        ({"seed": 1.5}, "seed"),
        ({"scenario_id": ""}, "scenario_id"),
        ({"speed": 2}, "unknown"),
        ({"traffic": [{"profile": "voip", "stations": "*"}]}, "profile"),
        ({"traffic": [{"profile": "web", "stations": "lab"}]}, "stations"),
        ({"traffic": [{"profile": "web", "stations": "*", "start_s": -1}]}, "start_s"),
        ({"traffic": [{"profile": "web", "stations": "*", "rate_mbps": 1}]}, "rate_mbps"),
        ({"traffic": [{"profile": "video", "stations": "*", "rate_mbps": 0}]}, "rate_mbps"),
        ({"traffic": [{"profile": "web", "stations": "*", "burst": 1}]}, "unknown"),
        ({"events": [{"at_s": 1, "type": "reboot", "ap": "ap1"}]}, "type"),
        ({"events": [{"at_s": 1, "type": "force_channel", "ap": "ap1"}]}, "channel"),
        ({"events": [{"at_s": 1, "type": "ap_down", "ap": "ap1", "channel": 6}]}, "channel"),
        ({"events": [{"at_s": 1, "type": "ap_down", "ap": "router"}]}, "ap"),
        ({"events": [{"at_s": 700, "type": "ap_down", "ap": "ap1"}]}, "duration_s"),
        ({"mobility": {"model": "random_walk", "groups": []}}, "mobility"),
    ],
)
def test_bad_scenarios_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_scenario(_with(**changes))


# ------------------------------------------------------------------ selectors and zones
ZONE_OF = {"sta1": "lecture_hall", "sta2": "lab", "sta10": "lecture_hall", "sta3": "corridor"}


@pytest.mark.parametrize(
    ("selector", "stations"),
    [
        ("*", ["sta1", "sta2", "sta3", "sta10"]),
        ("lecture_hall:*", ["sta1", "sta10"]),
        ("library:*", []),
        ("sta2", ["sta2"]),
    ],
)
def test_selectors_resolve_in_station_order(selector: str, stations: list[str]) -> None:
    assert resolve_selector(selector, ZONE_OF) == stations


def test_unknown_station_selector_is_rejected() -> None:
    with pytest.raises(ValueError, match="sta99"):
        resolve_selector("sta99", ZONE_OF)


def test_zones_follow_the_walks() -> None:
    walk = Walk("sta9", start_s=100.0, src=(10.0, 20.0), dst=(10.0, 50.0), speed_mps=1.0)
    assert zones_at(LAYOUT, STATIONS, [walk], t=99)["sta9"] == "corridor"
    assert zones_at(LAYOUT, STATIONS, [walk], t=130)["sta9"] == "lecture_hall"
    assert zones_at(LAYOUT, STATIONS, [walk], t=130)["sta1"] == "lecture_hall"
    assert zones_at(LAYOUT, STATIONS, [], t=0)["sta16"] == "library"


def test_a_station_outside_every_zone_is_an_error() -> None:
    walk = Walk("sta9", start_s=0.0, src=(10.0, 20.0), dst=(10.0, 2.0), speed_mps=1.0)
    with pytest.raises(ValueError, match="outside every zone"):
        zones_at(LAYOUT, STATIONS, [walk], t=100)


def test_orphans_join_the_nearest_ap_that_is_up() -> None:
    lab_point = (60.0, 50.0)
    assert nearest_up_ap(LAYOUT, lab_point, down=set()) == "ap2"
    assert nearest_up_ap(LAYOUT, (55.0, 40.0), down={"ap2"}) == "ap4"  # 20 m vs ap1 at 36 m


def test_no_ap_up_is_an_error() -> None:
    with pytest.raises(ValueError, match="no AP is up"):
        nearest_up_ap(LAYOUT, (0.0, 0.0), down={"ap1", "ap2", "ap3", "ap4"})


# ------------------------------------------------------------------ timeline
def test_timeline_groups_traffic_and_events_by_time() -> None:
    raw = _with(
        traffic=[
            {"profile": "video", "stations": "lab:*", "start_s": 10},
            {"profile": "web", "stations": "*", "start_s": 0},
            {"profile": "bulk", "stations": "sta5", "start_s": 10, "rate_mbps": 0.5},
        ],
        events=[{"at_s": 10, "type": "ap_down", "ap": "ap2"}],
    )
    spec = parse_scenario(raw)
    assert timeline(spec) == [
        Step(0.0, (spec.traffic[1],), ()),
        Step(10.0, (spec.traffic[0], spec.traffic[2]), (spec.events[0],)),
    ]


# ------------------------------------------------------------------ summaries
def _kpi(app_class: str, mbps: float, latency: float = 10.0, loss: float = 0.0) -> dict[str, Any]:
    return {
        "app_class": app_class,
        "throughput_mbps": mbps,
        "latency_ms": latency,
        "jitter_ms": 1.0,
        "loss_pct": loss,
    }


def test_summary_is_per_app_class() -> None:
    records = [_kpi("video", 1.0, 10), _kpi("video", 0.5, 30, 10), _kpi("web", 2.0, 20)]
    assert summarize_kpis(records) == {
        "video": {
            "records": 2,
            "throughput_mbps": 0.75,
            "latency_ms_p50": 20.0,
            "latency_ms_p95": 30.0,
            "loss_pct": 5.0,
        },
        "web": {
            "records": 1,
            "throughput_mbps": 2.0,
            "latency_ms_p50": 20.0,
            "latency_ms_p95": 20.0,
            "loss_pct": 0.0,
        },
    }


def test_p95_uses_nearest_rank() -> None:
    records = [_kpi("bulk", 1.0, float(ms)) for ms in range(1, 21)]  # 1..20 ms
    assert summarize_kpis(records)["bulk"]["latency_ms_p95"] == 19.0


@pytest.mark.parametrize(
    ("values", "deviation"),
    [([4.0, 4.0, 4.0], 0.0), ([4.0, 4.2, 3.8], 5.0), ([1.0, 3.0], 50.0)],
)
def test_max_deviation_from_the_mean(values: list[float], deviation: float) -> None:
    assert max_deviation_pct(values) == pytest.approx(deviation)


def test_deviation_needs_values() -> None:
    with pytest.raises(ValueError, match="no values"):
        max_deviation_pct([])
