"""Campus layout loader (testbed/layout.py): validation and seeded station placement."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from testbed.layout import CampusLayout, layout_from_dict, load_layout, place_stations

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPUS_V1 = REPO_ROOT / "config" / "campus_v1.yaml"


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CAMPUS_V1.read_text())
    return data


def test_campus_v1_loads() -> None:
    layout = load_layout(CAMPUS_V1)
    assert isinstance(layout, CampusLayout)
    assert [ap.name for ap in layout.aps] == ["ap1", "ap2", "ap3", "ap4"]
    assert layout.switches == ["s1", "s2"]
    assert layout.station_count == 20
    assert layout.max_ping_loss_pct == 2.0
    assert layout.reach_ping_count == 3


def test_checks_section_is_optional_and_defaults_to_strict(raw: dict[str, Any]) -> None:
    del raw["checks"]
    layout = layout_from_dict(raw)
    assert layout.max_ping_loss_pct == 0.0
    assert layout.reach_ping_count == 1


def test_stations_are_placed_inside_their_zone_with_margin() -> None:
    layout = load_layout(CAMPUS_V1)
    stations = place_stations(layout)
    assert len(stations) == layout.station_count
    for sta in stations:
        zone = layout.zones[sta.zone]
        x, y = sta.position
        assert zone.x_min + layout.margin_m <= x <= zone.x_max - layout.margin_m
        assert zone.y_min + layout.margin_m <= y <= zone.y_max - layout.margin_m


def test_station_names_ips_and_aps_follow_the_layout() -> None:
    layout = load_layout(CAMPUS_V1)
    stations = place_stations(layout)
    assert [s.name for s in stations] == [f"sta{i}" for i in range(1, 21)]
    assert stations[0].ip == "10.0.0.1/8"
    assert stations[-1].ip == "10.0.0.20/8"
    zone_ap = {ap.zone: ap.name for ap in layout.aps}
    assert all(s.ap == zone_ap[s.zone] for s in stations)
    counts = {z: sum(1 for s in stations if s.zone == z) for z in layout.zones}
    assert counts == layout.initial


def test_placement_is_deterministic_for_a_seed() -> None:
    layout = load_layout(CAMPUS_V1)
    assert place_stations(layout) == place_stations(layout)


def test_placement_changes_with_seed(raw: dict[str, Any]) -> None:
    other = copy.deepcopy(raw)
    other["stations"]["seed"] = 8
    a = place_stations(layout_from_dict(raw))
    b = place_stations(layout_from_dict(other))
    assert [s.position for s in a] != [s.position for s in b]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["aps"][0].update(channel=3), "channel"),
        (lambda d: d["aps"][0].update(zone="gym"), "unknown zone"),
        (lambda d: d["aps"].append(dict(d["aps"][0])), "duplicate"),
        (lambda d: d["aps"][0].update(position=[200, 10]), "outside"),
        (lambda d: d["stations"]["initial"].update(lab=6), "sum"),
        (lambda d: d["stations"]["initial"].update(gym=1), "unknown zone"),
        (lambda d: d["wired_links"].append(["ap9", "s1", 100]), "unknown node"),
        (lambda d: d["wired_links"][0].__setitem__(2, 0), "bandwidth"),
        (lambda d: d["zones"]["lab"].update(x=[80, 40]), "zone"),
        (lambda d: d["stations"].update(margin_m=50), "margin"),
        (lambda d: d["checks"].update(max_ping_loss_pct=150), "max_ping_loss_pct"),
        (lambda d: d["checks"].update(reach_ping_count=0), "reach_ping_count"),
    ],
)
def test_invalid_layouts_are_rejected(raw: dict[str, Any], mutate: Any, message: str) -> None:
    bad = copy.deepcopy(raw)
    mutate(bad)
    with pytest.raises(ValueError, match=message):
        layout_from_dict(bad)
